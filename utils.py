import re
import ast
import sys
import json
from loguru import logger

def extract_func_signature_from_code(func_name: str, code: str):
    """
    根据传入的func_name和代码字符串，找到对应函数的参数列表。
    返回：(func_name, param_list)
    """
    # 匹配所有def定义
    pattern = re.compile(r"def\s+(\w+)\s*\((.*?)\)", re.S)
    for match in pattern.finditer(code):
        name = match.group(1)
        param_str = match.group(2)
        if name == func_name:
            param_list = []
            for param in param_str.split(","):
                param = param.strip()
                if not param:
                    continue
                param_name = re.split(r"[:=]", param)[0].strip()
                param_list.append(param_name)
            return func_name, param_list
    raise ValueError(f"未找到指定函数: {func_name}")

def extract_buggy_code(task_data_json: dict, filename: str = "buggy_code.py"):
    """将代码保存到当前目录，返回文件路径"""
    full_code = task_data_json['declaration'] + task_data_json['buggy_solution']
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(full_code)
    logger.info(f"bug代码已经整合并保存到{filename}")
    return full_code

def write_str_to_file(str_code: str, filename: str = "tmp.py"):
    # Replace escaped newlines with actual newlines
    str_code = str_code.replace('\\n', '\n')
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(str_code)
    logger.info(f"code已经保存到{filename}")

def run_check_function(func_name: str, check_code: str, code_to_test: str):
    test_globals = {}
    exec(code_to_test, test_globals, test_globals)
    try:
        exec(check_code, test_globals, test_globals)
        logger.info(f"✅ 测试通过: {func_name} 函数的检查代码执行成功")
        return True
    except AssertionError as e:
        # 提供更详细的断言错误信息
        error_msg = str(e) if str(e) else "断言失败 - 函数输出与预期不符"
        logger.info(f"❌ 测试失败: {error_msg}")
        return False
    except Exception as e:
        # 提供更详细的异常信息
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else f"{type(e).__name__} (无详细信息)"
        logger.error(f"⚠️ 执行错误: {error_msg}")
        return False