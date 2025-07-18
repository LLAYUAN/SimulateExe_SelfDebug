import json
import re
from complete_cfg_builder import TextCFG
from utils import extract_buggy_code
from chat import chat_selfdebug, chat_merge_debug_results
from loguru import logger
from typing import List


def extract_individual_test_cases(test_code: str, func_name: str) -> List[str]:
    """
    从完整的测试代码中提取单个测试用例
    Args:
        test_code: 完整的测试代码字符串
        func_name: 函数名
    Returns:
        单个测试用例的列表
    """
    individual_tests = []
    
    # 移除check函数定义和调用
    test_lines = test_code.strip().split('\n')
    
    # 提取assert语句
    for line in test_lines:
        line = line.strip()
        if line.startswith('assert'):
            # 为每个assert创建一个完整的测试函数
            test_func = f"""
                        def test_{func_name}():
                            {line}

                        test_{func_name}()
                        """
            individual_tests.append(test_func)
    
    return individual_tests


def extract_test_cases_from_example(example_test: str, func_name: str) -> List[str]:
    """
    从example_test中提取测试用例
    Args:
        example_test: 示例测试代码
        func_name: 函数名
    Returns:
        单个测试用例的列表
    """
    individual_tests = []
    
    # 分析example_test的结构
    lines = example_test.strip().split('\n')
    
    # 查找assert语句
    for line in lines:
        line = line.strip()
        if line.startswith('assert'):
            # 创建独立的测试函数
            test_func = f"""
def test_{func_name}():
    {line}

test_{func_name}()
"""
            individual_tests.append(test_func)
    
    return individual_tests


def selfdebug_multi(task_id: int = 5):
    """
    多轮对话调试函数
    Args:
        task_id: 要调试的任务ID
    """
    logger.info(f"开始多轮调试任务 {task_id}")
    
    # 读取数据
    with open("dataset_test/humanevalfix/humanevalpack.jsonl", "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i == task_id + 1:
                data = json.loads(line.strip())
                break
        else:
            logger.error(f"文件中没有第{task_id}行")
            return
    
    # 提取基本信息
    buggy_code = extract_buggy_code(data)
    func_name = data["entry_point"]
    task_description = data["docstring"]
    
    # 构建CFG
    try:
        textcfg = TextCFG("buggy_code.py", func_name)
        cfg_text = textcfg.cfg_text
    except Exception as e:
        logger.warning(f"CFG构建失败: {e}")
        cfg_text = ""
    
    logger.info(f"Function name: {func_name}")
    logger.info(f"Task description: {task_description}")
    
    # 提取测试用例
    test_cases = []
    
    # 从example_test中提取
    if 'example_test' in data and data['example_test']:
        example_test_cases = extract_test_cases_from_example(data['example_test'], func_name)
        test_cases.extend(example_test_cases)
        logger.info(f"从示例测试中提取了 {len(example_test_cases)} 个测试用例")
    
    if not test_cases:
        logger.error("没有找到任何测试用例")
        # 当没有测试用例时，直接使用chat_merge_debug_results进行调试
        logger.info("=== 没有测试用例，直接使用合并调试功能 ===")
        
        # 创建一个基本的调试结果作为输入
        basic_debug_result = {
            "test_case": "No test cases available",
            "bug_analysis": "No specific test cases to analyze, performing general code analysis",
            "corrected_code": buggy_code,
            "explanation": "No test cases provided, requiring general debugging approach"
        }
        
        individual_results = [json.dumps(basic_debug_result, ensure_ascii=False)]
        
        try:
            final_corrected_code = chat_merge_debug_results(
                buggy_code=buggy_code,
                individual_results=individual_results,
                task_description=task_description
            )
            
            logger.info("=== 直接调试完成 ===")
            logger.info("最终修正代码：")
            logger.info("="*50)
            logger.info(final_corrected_code)
            logger.info("="*50)
            
            return final_corrected_code
            
        except Exception as e:
            logger.error(f"直接调试失败: {e}")
            return buggy_code
    
    logger.info(f"总共提取了 {len(test_cases)} 个测试用例")
    
    # 第一阶段：为每个测试用例进行单独调试
    individual_results = []
    
    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"=== 调试测试用例 {i}/{len(test_cases)} ===")
        logger.info(f"测试用例内容：\n{test_case}")
        
        try:
            # 直接调用chat_selfdebug
            full_debug_result = chat_selfdebug(
                buggy_code=buggy_code,
                example_test=test_case,
                task_description=task_description,
                text_cfg=cfg_text
            )
            
            # 从chat_selfdebug的输出中提取需要的信息
            try:
                full_debug_json = json.loads(full_debug_result)
                corrected_code = full_debug_json.get("corrected_code", buggy_code)
                explanation = full_debug_json.get("explanation", "No explanation provided")
                
                # 提取第一个测试用例的分析信息（如果存在）
                overall_analysis = full_debug_json.get("overall_analysis", {})
                
                # 构建简化的结果格式（保持与原来兼容）
                simplified_result = {
                    "test_case": test_case.strip(),
                    "bug_analysis": overall_analysis.get("common_patterns", "Analysis from chat_selfdebug"),
                    "corrected_code": corrected_code,
                    "explanation": explanation
                }
                
                result = json.dumps(simplified_result, ensure_ascii=False)
                individual_results.append(result)
                logger.info(f"测试用例 {i} 调试完成")
                
                # 打印结果摘要
                logger.info(f"  Bug分析: {simplified_result.get('bug_analysis', 'N/A')[:100]}...")
                logger.info(f"  修正说明: {simplified_result.get('explanation', 'N/A')[:100]}...")
                
            except json.JSONDecodeError as e:
                logger.warning(f"测试用例 {i} 的chat_selfdebug结果JSON格式有误: {e}")
                # 创建一个简单的结果
                simplified_result = {
                    "test_case": test_case.strip(),
                    "bug_analysis": "JSON parsing failed for chat_selfdebug result",
                    "corrected_code": buggy_code,
                    "explanation": f"Failed to parse chat_selfdebug result: {str(e)}"
                }
                result = json.dumps(simplified_result, ensure_ascii=False)
                individual_results.append(result)
                
        except Exception as e:
            logger.error(f"测试用例 {i} 调试失败: {e}")
            # 创建一个错误结果
            error_result = {
                "test_case": test_case,
                "expected_behavior": "Unknown due to error",
                "actual_behavior": "Error occurred",
                "bug_analysis": f"调试过程中发生错误: {str(e)}",
                "corrected_code": buggy_code,
                "explanation": f"调试失败: {str(e)}"
            }
            individual_results.append(json.dumps(error_result, ensure_ascii=False))
    
    if not individual_results:
        logger.error("所有测试用例调试都失败了")
        return
    
    logger.info(f"=== 第一阶段完成，成功调试了 {len(individual_results)} 个测试用例 ===")
    
    # 第二阶段：合并所有结果，生成最终修正代码
    logger.info("=== 开始第二阶段：合并调试结果 ===")
    
    try:
        final_corrected_code = chat_merge_debug_results(
            buggy_code=buggy_code,
            individual_results=individual_results,
            task_description=task_description
        )
        
        logger.info("=== 多轮调试完成 ===")
        logger.info("最终修正代码：")
        logger.info("="*50)
        logger.info(final_corrected_code)
        logger.info("="*50)
        
        return final_corrected_code
        
    except Exception as e:
        logger.error(f"合并调试结果失败: {e}")
        return buggy_code

if __name__ == "__main__":
    selfdebug_multi(5)