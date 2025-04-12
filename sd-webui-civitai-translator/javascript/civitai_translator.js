"use strict";

function getActiveTabType() {
    var currentTab = gradioApp().querySelector('#tabs > .tabitem[id^=tab_]:not([style*="display: none"])').id;
	return currentTab.replace('tab_','');    
}

onUiLoaded(() => {

	return;
	let tab_prefix_list = ["txt2img", "img2img"];

	for (const tab_prefix of tab_prefix_list) {
		//if (tab_prefix != getActiveTabType()) {continue;}
		
		let my_toolbar_id = tab_prefix + "_" + "tools";
		let my_toolbar = gradioApp().querySelector('#'+my_toolbar_id+' .form');
		let paste_btn = gradioApp().getElementById('paste');
		if (!paste_btn) {
			console.log("can not find paste button with id: paste");
			continue;
		}
		// add refresh button to toolbar
		let cv_translate = document.createElement("button");
		cv_translate.innerHTML = "↔";
		cv_translate.title = "Translate Civitai's MetaData";
		cv_translate.className = paste_btn.className;
		cv_translate.onclick = translate_civitai_metadata;
		my_toolbar.appendChild(cv_translate);
	}

});

function translate_civitai_metadata() {
	var currentTab=(document.querySelector('#tab_txt2img').style['display']!='none'?'#txt2img':'#img2img'),
		re=new RegExp('Civitai resources: .*]'),
		prompt_area=document.querySelector(currentTab+'_prompt textarea'),
		pormpt_neg_area=document.querySelector(+currentTab+'_neg_prompt textarea'),
		civitai_data=prompt_area.value.match(re),
		needToTranslate=0,
		model='', loras="", pos_ti='', neg_ti='', vae='', resources=[], notTranslateable='';

	if (!civitai_data) {console.log("Nothing to do for Civitai-Translator"); return;}
	if (civitai_data) {
		resources=JSON.parse(civitai_data[0].replace("Civitai resources: ",''));
		console.log(resources);
	}
	needToTranslate=resources.length;
	prompt_area.value=prompt_area.value.replace(civitai_data,'');
	//updateInput(prompt_area);
	
	const model_endings = /\.safetensors$|\.pt$|\.ckpt$/g;
	resources.forEach(
		function(ressource){
			//console.log(ressource.modelVersionId);
			let xhr = new XMLHttpRequest();
			xhr.open('GET', 'https://civitai.com/api/v1/model-versions/'+ressource.modelVersionId+'/'); //
			xhr.send();
			xhr.onload = function() {
				if (xhr.status=="200") {
					var model_data=JSON.parse(xhr.response),
						modelName=model_data.model.name,
						modelType=model_data.model.type.toLowerCase(),
						modelHash=model_data.files[0].hashes.AutoV2.toLowerCase(),
						modelFileName=model_data.files[0].name,
						//url='https://civitai.com/search/models?&query='+modelHash;
						url="https://civitai.com/models/"+model_data.modelId+"?modelVersionId="+model_data.id;
					
					console.log(model_data,modelName,'#'+modelType+'#',modelHash);

					if(modelType=="checkpoint") {
						console.log('Found Model');
						model=" Model hash: "+modelHash+", Model: "+ modelName+ ',';
						//this is a bit cheating, but it didn't work in the line with the checkpoints 
						loras+='#Checkpoint-Info ('+modelName+'): ' +url+ " \n ";
					} else if(modelType=="lora" || modelType=="locon" || modelType=="lycoris") {						
						if (model_data.files.length>1) {
							for(var m=0;m<model_data.files.length;m++) {
								if (model_data.files[m].name.search(model_endings)>0) {
									modelFileName=model_data.files[m].name;
									modelHash=model_data.files[m].hashes.AutoV2.toLowerCase();
									//url='https://civitai.com/search/models?&query='+modelHash;
									break;
								}
							}
						}
						console.log('Found Lora/Locon/Lycoris');
						loras+='<lora:'+modelFileName.replace('.safetensors','')+':'+ressource.weight+">, #"+url+" #" + modelName + "\n ";  
						
					} else if(modelType=="vae") {
							vae=" VAE: "+ modelName + ', '; 
					
					} else if(modelType=="embed" || modelType=="textualinversion") {
						var keyword=modelFileName.replace('.safetensors','').replace('.pt','');
						if (!prompt_area.value.includes(keyword)) { // if TI not already in prompt...
							if (keyword.includes('bad') || keyword.includes('neg')){
								neg_ti += ' '+keyword+', #'+url+" #" + modelName + "\n ";  
							} else {
								pos_ti+=' '+keyword+', #'+url+" #" + modelName + "\n ";  
							}
						}
						
					} else {
						notTranslateable+="\n# Can't translate modelId:"+ ressource.modelVersionId;
					}
				} else {
					console.log("No OK(200) From Civitai's ApPI");
					notTranslateable+="\n# Can't translate modelId: "+ ressource.modelVersionId;
				}
				needToTranslate--;				
				console.log("NTT:"+needToTranslate)
				if(needToTranslate<=0) {
					var newPrompt=prompt_area.value,
						fistNegativePrompt=prompt_area.value.search('Negative prompt:'),
						lastPositivePrompt=fistNegativePrompt-1,
						stepPosition=prompt_area.value.search('Steps:');

					if (lastPositivePrompt<0) {
						lastPositivePrompt=stepPosition-1;
					}

					newPrompt+= model;
					newPrompt+= vae;
					newPrompt+= "RNG: CPU, "; // from what I see, images get closer to Civitai's Generator with CPU-RNG
					newPrompt=newPrompt.substr(0, lastPositivePrompt) + "\n " + loras + " " + newPrompt.substr(lastPositivePrompt);
					newPrompt=newPrompt.substr(0, lastPositivePrompt) + "\n " + pos_ti + " " + newPrompt.substr(lastPositivePrompt);
					newPrompt+=notTranslateable;

					fistNegativePrompt=newPrompt.search('Negative prompt:');
					stepPosition=newPrompt.search('Steps:')-1;
					if (fistNegativePrompt<0) {
						newPrompt=newPrompt.substr(0, stepPosition) + "\n Negative prompt: " + neg_ti + " " + newPrompt.substr(stepPosition);
					} else {
						newPrompt=newPrompt.substr(0, stepPosition) + "\n " + neg_ti + " " + newPrompt.substr(stepPosition);
					}

					prompt_area.value=newPrompt.replace(civitai_data,'');
					updateInput(prompt_area);
				}
			}
		}
	);
	return resources;
}