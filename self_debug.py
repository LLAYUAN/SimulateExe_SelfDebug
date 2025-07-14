import json
from complete_cfg_builder import TextCFG
from utils import extract_buggy_code
from chat import chat_selfdebug

def selfdebug():
    """测试extract_testcases函数"""
    
    # 读取第i行数据
    with open("data/humanevalfix/humanevalpack.jsonl", "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i == 42:
                data = json.loads(line.strip())
                break
        else:
            print("文件中没有第3行")
            return
    
    buggy_code = extract_buggy_code(data)
    example_test = data["example_test"]
    func_name = data["entry_point"]
    textcfg = TextCFG("buggy_code.py", func_name)
    task_description = data["docstring"]
    
    
    print(f"Function name: {func_name}")
    print(f"Example test: {example_test}")
    print(f"Task description: {task_description}")
    print(f"TextCFG: {textcfg.cfg_text}")
    print(f"Block num: {textcfg.block_num}")
    print(f"Connections: {len(textcfg.connections)}")
    print("Connections details:")
    for conn in textcfg.connections:
        print(f"  {conn['from']} --{conn['type']}--> {conn['to']}")
    print("\n" + "="*50)

    print("Testing selfdebug function...")
    result = chat_selfdebug(buggy_code, example_test, task_description, textcfg.cfg_text)
    print("\nDebugging result:")
    print(result)

    try:
        result_json = json.loads(result)
        print(f"\nJSON format is correct")
        if 'corrected_code' in result_json:
            print(f"Has corrected code: {'Yes' if result_json['corrected_code'] else 'No'}")
            # 显示修正后的代码
            if result_json['corrected_code']:
                print("\nCorrected code:")
                print("="*30)
                print(result_json['corrected_code'])
                print("="*30)

    except json.JSONDecodeError as e:
        print(f"JSON format error: {e}")

if __name__ == "__main__":
    print("Starting to test new functions...")
    selfdebug() 