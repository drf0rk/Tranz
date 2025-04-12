from modules import script_callbacks
import gradio as gr
import requests
import re
import json
import os
import glob

from modules.styles import extract_style_text_from_prompt
from modules.ui_components import ToolButton
from modules.shared import opts

js = """
function get_prompt() {    
    return document.querySelector('#txt2img_prompt textarea').value
}
"""

js_out = """
function out_prompt() {
    setTimeout(function(){
        gradioApp().querySelector('#txt2img_prompt textarea').value= gradioApp().querySelector('#hidden_output textarea').value.trim()
        document.querySelector('#txt2img_prompt textarea').value= document.querySelector('#hidden_output textarea').value.trim()
        //Gradio doesn't "get" the change, unless there's an input event in the text-area...
        var e = document.querySelector('#txt2img_prompt textarea');
        var ev = new Event('input', {  bubbles: true,  cancelable: true });
        e.dispatchEvent(ev);
    }, 200);
    return true
}
"""

def find_seed(data):
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "seed":
                return value
            result = find_seed(value)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_seed(item)
            if result is not None:
                return result
    return None

def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in files:
            return os.path.join(root, name)


def translate_input(input_txt):
    global found_models

    try: #Trys to translate a newer "txt-to-image hires" format, into old infos before proceeding.
        translate_sampler = {"euler_ancestral": "Euler a"}
        data=json.loads(input_txt)

        prompt_data = json.loads(data['extraMetadata'])

        prompt =  prompt_data['prompt']
        negprompt = prompt_data['negativePrompt']
        steps = prompt_data['steps']
        cfg=  prompt_data['cfgScale']
        if 'seed' in prompt_data:
            seed = prompt_data['seed']
        else:
            seed = find_seed(data)

        sampler = prompt_data['sampler']
        sampler = sampler if not sampler in translate_sampler else translate_sampler[sampler]

        width = 0
        height = 0

        scale = None
        scaleHint = None
        for obj in data:
            if 'class_type' in data[obj]:
                if data[obj].get('class_type') == 'EmptyLatentImage':
                    scale = data[obj]
                    width = 0 if not 'inputs' in scale else scale['inputs']['width']
                    height = 0 if not 'inputs' in scale else scale['inputs']['height']
                    break
                if data[obj].get('class_type') == 'ImageScale':
                    scaleHint = data[obj]

        if width == 0 and height==0 and scaleHint:
            width = 1024 if not 'inputs' in scaleHint else scaleHint['inputs']['width']
            height = 1024 if not 'inputs' in scaleHint else scaleHint['inputs']['height']
            negprompt += "\n# ⚠ Size guessed AFTER upscale ⚠\n"

        cfg_string = f"Steps:{steps}, Sampler: {sampler}, CFG scale: {cfg}, Seed: {seed}, Size: {width}x{height},"

        extra=data['extra']['airs']
        models={}
        for e in extra:
            d=e.split(':')
            modelIds=d[5].split('@')
            models[modelIds[1]]= { 'type': d[3], 'baseVersion':modelIds[0] }

        civitai_resources='Civitai resources: ['
        res = prompt_data['resources']

        for r in res:
            resource = str(r['modelVersionId'])
            strength = 0 if not "strength" in r else r['strength']
            m=models[resource]
            t = m['type']
            if t != 'checkpoint':
                civitai_resources += '{' + f'"type": "{t}", "weight": {strength}, "modelVersionId": {resource}'+'}'
            else:
                civitai_resources += '{' + f'"type": "{t}", "modelVersionId": {resource}'+'}'

        civitai_resources += ']'


        txt=f"\n{prompt}\nNegative prompt:{negprompt}\n{cfg_string}, {civitai_resources} \n\n"

        print (txt)
        input_txt = txt
    except Exception as error:
        print("An exception occurred:", error)
        print("Problem with JSON-Extract, trying standard route")

    civitai_data = re.split(r"Civitai resources.*: \[",input_txt)

    if len(civitai_data)<2:
        return "#Nothing to Translate?⚠\n"+ input_txt

    prompt_area_value = civitai_data[0]
    new_prompt = prompt_area_value
    readable_data=civitai_data[1];
    if "Civitai metadata" in civitai_data[1]:
        readable_data=civitai_data[1].split('Civitai metadata')[0]
    print(readable_data)
    resources_raw=re.findall('\{[^}]*}',readable_data)
    
    resources=[item for item in resources_raw if item]
    need_to_translate = len(resources)

    model_endings = re.compile(r'\.safetensors$|\.pt$|\.ckpt$')

    model, loras, pos_ti, neg_ti, vae, not_translateable = '', '', '', '', '', ''

    rq_session = requests.Session()

    for resource in resources:
        resource = json.loads(resource)
        if not resource:
            need_to_translate -= 1
            continue
        print(resource)
        response = rq_session.get(f'https://civitai.com/api/v1/model-versions/{resource["modelVersionId"]}/')

        if response.status_code == 200:
            model_data = response.json()
            model_name = model_data['model']['name']
            model_type = model_data['model']['type'].lower()
            if len(model_data['files']) == 0:
                loras += f'#Model "{model_name}"({model_type}) no longer available?! ⚠\n'
                loras += f"#      try: https://civitai.com/models/{model_data['modelId']}?modelVersionId={model_data['id']}\n"
                need_to_translate -= 1
                continue

            model_hash = model_data['files'][0]['hashes']['AutoV2'].lower()
            model_file_name = model_data['files'][0]['name']
            url = f"https://civitai.com/models/{model_data['modelId']}?modelVersionId={model_data['id']}"

                
            file_matches = [item for item in found_models if model_file_name in item]
            print(model_name, f'#{model_type}#', model_hash, model_data['files'][0]['name'], file_matches)
            file_matched = "☑" if file_matches else "🔎"

            if model_type == "checkpoint":
                print('Found Model')
                model = f" Model hash: {model_hash}, Model: {model_name},"
                loras += f'#Checkpoint-Info ({model_name}): {url} {file_matched}\n '
            elif model_type in ["lora", "locon", "lycoris"]:
                if len(model_data['files']) > 1:
                    for file in model_data['files']:
                        if model_endings.search(file['name']):
                            model_file_name = file['name']
                            model_hash = file['hashes']['AutoV2'].lower()
                            break
                print('Found Lora/Locon/Lycoris')
                loras += f'<lora:{model_file_name.replace(".safetensors", "")}:{resource["weight"]}>, #{url} #{model_name} {file_matched}\n '
            elif model_type == "vae":
                vae = f" VAE: {model_name}, "
            elif model_type in ["embed", "textualinversion"]:
                keyword = model_file_name.replace('.safetensors', '').replace('.pt', '')
                if keyword not in prompt_area_value:
                    if 'bad' in keyword or 'neg' in keyword:
                        neg_ti += f' {keyword}, #{url} #{model_name} {file_matched}\n '
                    else:
                        pos_ti += f' {keyword}, #{url} #{model_name} {file_matched}\n '
            else:
                not_translateable += f"\n# Can't translate modelId: {resource['modelVersionId']} "
        else:
            print("No OK(200) From Civitai's API, instead we got:" + str(response.status_code))

        need_to_translate -= 1
        print(f"Need to Translate: {need_to_translate}")

    if need_to_translate <= 0:
        new_prompt = prompt_area_value
        first_negative_prompt = prompt_area_value.find('Negative prompt:')
        last_positive_prompt = first_negative_prompt - 1
        step_position = prompt_area_value.find('Steps:')

        if last_positive_prompt < 0:
            last_positive_prompt = step_position - 1

        new_prompt += model + vae + "RNG: CPU, "
        new_prompt = new_prompt[:last_positive_prompt] + f"\n {loras} " + new_prompt[last_positive_prompt:]
        new_prompt = new_prompt[:last_positive_prompt] + f"\n {pos_ti} " + new_prompt[last_positive_prompt:]
        new_prompt += not_translateable

        first_negative_prompt = new_prompt.find('Negative prompt:')
        step_position = new_prompt.find('Steps:') - 1

        if first_negative_prompt < 0:
            new_prompt = new_prompt[:step_position] + f"\n Negative prompt: {neg_ti} " + new_prompt[step_position:]
        else:
            new_prompt = new_prompt[:step_position] + f"\n {neg_ti} " + new_prompt[step_position:]
        
    return new_prompt

def core(self):  # ui stuff
    #with gr.Row(elem_id="txt2img_tools", variant="stretch"):
    translate = ToolButton(value="↔", elem_id="translate_button", tooltip="Translate Civitai Meta-data")
    hidden_output = gr.Textbox(elem_id="hidden_output", value="translate_out", visible=False)
    def transl(input_text):
        return translate_input(input_text)
    
    translate.click(fn=transl, inputs=hidden_output, outputs=hidden_output, _js=js).then(None,_js=js_out)


def style_apply_button(component, **kwargs):
    if kwargs.get("elem_id") == "txt2img_style_apply":
        core(kwargs)

models_directory=os.getcwd()+"/models/"
found_models=glob.glob('**/*.pt', root_dir=models_directory, recursive=True)
found_models+=glob.glob('**/*.safetensors', root_dir=models_directory, recursive=True)
found_models+=glob.glob('**/*.ckpt', root_dir=models_directory, recursive=True)

script_callbacks.on_after_component(style_apply_button)




