from openai import OpenAI
from loguru import logger
import time
import re
import json
from typing import List

GPT_MODEL = "openai/gpt-4o-mini"
GPT_BASE_URL = "https://openrouter.ai/api/v1"
GPT_API_KEY = "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"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_KEY = "sk-faebc4b10dd047d58459d9d5f97dcf21"

client = OpenAI(
    base_url=GPT_BASE_URL,
    api_key=GPT_API_KEY,
    timeout=180.0,  # 设置2分钟超时
)

MAX_VLLM_RETRIES = 3  # 减少重试次数
RETRY_DELAY = 2  # 增加重试延迟
TEMPERATURE = 0.8 
TOTAL_PROMPT_TOKENS = 0
TOTAL_COMPLETION_TOKENS = 0

def get_completion_with_retry(messages, model=GPT_MODEL, MAX_VLLM_RETRIES=MAX_VLLM_RETRIES):
    global TOTAL_PROMPT_TOKENS, TOTAL_COMPLETION_TOKENS
    for attempt in range(MAX_VLLM_RETRIES):
        try:
            logger.info(f"Attempting LLM call (attempt {attempt + 1}/{MAX_VLLM_RETRIES})")
            
            start_time = time.time()
            chat_response = client.chat.completions.create(
                messages=messages,
                model=model,
                temperature=TEMPERATURE,
                response_format={
                    'type':'json_object',
                },
                timeout=120.0,  # 设置请求超时
            )
            
            call_duration = time.time() - start_time
            logger.info(f"LLM call completed in {call_duration:.2f}s")
            
            response = chat_response.choices[0].message.content
            logger.info(f"收到API响应，长度: {len(response) if response else 0} 字符")
            
            # 验证响应是否为空或过短
            if not response or len(response.strip()) < 10:
                logger.error(f"响应为空或过短: {len(response) if response else 0} 字符")
                logger.error(f"响应内容: {response}")
                raise ValueError(f"Empty or too short response: {len(response) if response else 0} chars")
            
            # 快速验证JSON格式
            logger.info("开始验证JSON格式...")
            try:
                json.loads(response)
                logger.info("JSON格式验证通过")
            except json.JSONDecodeError as e:
                # 添加详细的错误调试信息
                logger.error("="*50)
                logger.error("get_completion_with_retry中JSON解析失败！详细信息如下：")
                logger.error(f"JSON错误详情: {str(e)}")
                logger.error(f"响应总长度: {len(response) if response else 0} 字符")
                logger.error(f"响应内容前500字符: {response[:500] if response else 'None'}...")
                logger.error(f"响应内容后100字符: {response[-100:] if response and len(response) > 100 else 'N/A'}...")
                
                # 检查错误位置附近的内容
                error_char_pos = getattr(e, 'pos', None)
                if error_char_pos and response:
                    start_pos = max(0, error_char_pos - 50)
                    end_pos = min(len(response), error_char_pos + 50)
                    logger.error(f"错误位置附近内容 (位置{error_char_pos}前后50字符):")
                    logger.error(f"'{response[start_pos:end_pos]}'")
                    logger.error(f"错误字符位置: {'^' * (error_char_pos - start_pos)}")
                
                logger.error("="*50)
                raise ValueError(f"Invalid JSON response: {str(e)[:100]}...")
            
            # Update token counts
            TOTAL_PROMPT_TOKENS += chat_response.usage.prompt_tokens
            TOTAL_COMPLETION_TOKENS += chat_response.usage.completion_tokens
            
            logger.info(f"LLM call successful, response length: {len(response)} chars")
            return response
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"LLM call failed (attempt {attempt + 1}/{MAX_VLLM_RETRIES}): {error_msg[:200]}...")
            
            # 如果是JSON解析相关错误，提供额外的上下文信息
            if "Invalid JSON response" in error_msg or "JSONDecodeError" in error_msg or "Expecting value" in error_msg:
                logger.error("这是JSON解析错误，可能的原因：")
                logger.error("1. API返回了非JSON格式的内容（HTML错误页面、纯文本等）")
                logger.error("2. API响应被截断")
                logger.error("3. API返回了空响应")
                logger.error("4. 响应中包含无效的JSON字符")
            
            if attempt < MAX_VLLM_RETRIES - 1:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error("Max retries reached. Giving up.")
                raise Exception(f"All {MAX_VLLM_RETRIES} attempts failed. Last error: {error_msg}")

def direct_fix_code(task_description: str, test_case: str, buggy_code: str) -> str:
    """
    直接调用大模型修复代码的函数
    Args:
        task_description: 任务描述
        test_case: 测试用例
        buggy_code: 错误的代码
    Returns:
        修复后的代码
    """
    prompt = f"""
    You are an expert Python programmer. I will provide you with a buggy Python function along with its task description and test case. 
    Your job is to analyze the bug and provide the corrected version of the code.

    ### Task Description
    {task_description}

    ### Test Case
    {test_case}

    ### Buggy Code
    ```python
    {buggy_code}
    ```

    ### Requirements
    1. Analyze the buggy code carefully and identify the issues
    2. Fix all bugs to make the code pass the provided test case
    3. Ensure the corrected code fulfills the task description
    4. Keep the original function signature and structure as much as possible
    5. Provide clean, readable code without extra comments
    6. Include all necessary import statements for the corrected code to run properly

    ### EXAMPLE JSON OUTPUT
    {{"fixed_code": "def function_name(params):\\n    # corrected implementation\\n    return result"}}

    Please output only the JSON format with the fixed code.
    """

    messages = [
        {'role': 'system', 'content': "You are an expert Python programmer specialized in debugging and fixing code."},
        {'role': 'user', 'content': prompt},
    ]

    try:
        response = get_completion_with_retry(messages)
        logger.info(f"direct_fix_code response: {response}")
        
        # 解析JSON响应
        try:
            data = json.loads(response)
            fixed_code = data.get("fixed_code", "")
            
            if not fixed_code:
                logger.warning("fixed_code字段为空，返回原始代码")
                return buggy_code
                
            return fixed_code.strip()
        except json.JSONDecodeError as e:
            logger.error("="*50)
            logger.error("direct_fix_code中JSON解析失败！详细信息如下：")
            logger.error(f"JSON错误详情: {str(e)}")
            logger.error(f"响应总长度: {len(response) if response else 0} 字符")
            logger.error(f"响应内容前500字符: {response[:500] if response else 'None'}...")
            logger.error(f"响应内容后100字符: {response[-100:] if response and len(response) > 100 else 'N/A'}...")
            logger.error("="*50)
            return buggy_code
        
    except Exception as e:
        logger.error(f"direct_fix_code出错: {e}")
        return buggy_code

# - You MUST obey the following loop handling rules to reduce the output length:
# **LOOP HANDLING RULES (CRITICAL FOR REDUCING OUTPUT):**
# - For loops (while/for), use abbreviated execution format to avoid excessive output:
#   * Show the first 2 iterations in detail with step-by-step execution
#   * Use "... (skipping middle iterations) ..." to represent intermediate iterations
#   * Show the last 1-2 iterations in detail (when loop condition becomes false or changes pattern)
#   * Always show the final variable states after loop completion
# - Example format for loop:
#   ```
#   Step 3 Block 2: while n > 1: -> condition: n=5 > 1 is True
#   Step 4 Block 3: n = n * 2 + 1 -> n: 5 → (5*2)+1 = 11
#   Step 5 Block 2: while n > 1: -> condition: n=11 > 1 is True  
#   Step 6 Block 3: n = n * 2 + 1 -> n: 11 → (11*2)+1 = 23
#   ... (skipping middle iterations) ...
#   Step X Block 2: while n > 1: -> condition: n=2 > 1 is True
#   Step Y Block 3: n = n * 2 + 1 -> n: 2 → (2*2)+1 = 5
#   Step Z Block 2: while n > 1: -> condition: n=1 > 1 is False (exit loop)
#   ```
#- If there is a loop in the code, you should use "..." to skip the middle part of the loop instead of executing the loop step by step, But you should give variable values of the first two and last two iterations of the loop.
#2. **Execution Trace Accuracy**: The code is buggy and may not yield the correct output in the test cases. Therefore, do not rely on the output in the test cases. Instead, execute the buggy code to obtain the actual output.


def chat_merge_debug_results(buggy_code: str, individual_results: List[str], task_description: str) -> str:
    """
    合并多个单独测试用例的调试结果，生成最终的修正代码
    Args:
        buggy_code: 原始错误代码
        individual_results: 每个测试用例的调试结果列表
        task_description: 任务描述
    Returns:
        最终的修正代码
    """
    # 解析所有个别结果
    parsed_results = []
    for result in individual_results:
        try:
            parsed = json.loads(result)
            parsed_results.append(parsed)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse individual result: {e}")
            continue
    
    if not parsed_results:
        logger.error("No valid individual results to merge")
        return buggy_code
    
    # 构建合并提示
    individual_analyses = ""
    for i, result in enumerate(parsed_results, 1):
        individual_analyses += f"""
### Analysis {i}:
**Test Case:** {result.get('test_case', 'Unknown')}
**Bug Analysis:** {result.get('bug_analysis', 'No analysis')}
**Proposed Fix:** 
```python
{result.get('corrected_code', 'No code')}
```
**Explanation:** {result.get('explanation', 'No explanation')}

"""

    prompt = f"""
You are an expert Python programmer. You have received multiple individual analyses of a buggy function, each focused on a specific test case. Your task is to synthesize all these analyses and provide a single, comprehensive corrected version that fixes all identified issues.

### Task Description
{task_description}

### Original Buggy Code
```python
{buggy_code}
```

### Individual Test Case Analyses
{individual_analyses}

### Synthesis Instructions

1. **Review all analyses**: Examine each individual analysis and proposed fix
2. **Identify common patterns**: Look for consistent issues across multiple test cases
3. **Resolve conflicts**: If different analyses suggest different fixes, determine the best approach
4. **Create unified solution**: Develop a single corrected version that addresses all identified issues
5. **Ensure completeness**: Make sure the final solution works for all test cases mentioned

### JSON Output Format
Please output strictly in the following JSON format:
{{
    "synthesis_analysis": "Analysis of how you combined the individual results",
    "common_issues": "List of issues that appeared across multiple test cases",
    "resolution_strategy": "How you resolved any conflicting suggestions",
    "final_corrected_code": "Complete final corrected code with proper imports",
    "comprehensive_explanation": "Detailed explanation of all changes made and why"
}}

### Quality Requirements
1. **Comprehensive**: Address all issues found in individual analyses
2. **Consistent**: Ensure the solution works for all test cases
3. **Clean**: Provide well-structured, readable code
4. **Complete**: Include all necessary imports and maintain function signature
5. **Accurate**: Ensure the final code correctly implements the task requirements

Begin your synthesis now.
"""

    messages = [
        {'role': 'system', 'content': "You are an expert Python programmer specializing in synthesizing multiple debugging analyses into a unified solution."},
        {'role': 'user', 'content': prompt}
    ]

    try:
        response = get_completion_with_retry(messages)
        logger.info(f"merge debug response: {response}")
        
        # 验证JSON格式
        try:
            result_json = json.loads(response)
            return result_json.get('final_corrected_code', buggy_code)
        except json.JSONDecodeError as e:
            logger.error(f"Merge debug JSON parsing failed: {str(e)}")
            return buggy_code
            
    except Exception as e:
        logger.error(f"Merge debug error: {e}")
        return buggy_code


def chat_selfdebug(buggy_code: str, example_test: str, task_description: str, text_cfg: str = "") -> str:
    """
    自调试函数，提供更详细的CoT推理过程
    Args:
        buggy_code: 错误的代码
        example_test: 测试用例代码字符串
        task_description: 任务描述
        text_cfg: 文本形式的控制流图
    Returns:
        JSON格式的调试结果
    """
    # print(f"text_cfg in chat_selfdebug: {text_cfg}")
    # print(f"buggy_code in chat_selfdebug: {buggy_code}")
    # print(f"example_test in chat_selfdebug: {example_test}")
    # print(f"task_description in chat_selfdebug: {task_description}")
    prompt = f"""
You are an expert Python programmer and debugger. Your task is to systematically analyze buggy code using detailed Chain-of-Thought reasoning and provide a corrected version.

### Task Description
{task_description}

### Buggy Code
```python
{buggy_code}
```

### Control Flow Graph (CFG)
{text_cfg if text_cfg else "No CFG provided"}

### Test Cases
```python
{example_test}
```

### Systematic Analysis Instructions

You must analyze each test case using the following 3-step process:

**Step 1: Simulate execution with test case inputs**
- Should ONLY rely on the CFG and the buggy code, DO NOT rely on the test cases and task description when executing the code.
- Start with the initial variable state from each test case input
- Execute the code following the CFG path step by step, starting from the Entry Point and ending at END (the Entry Point and END are Given in the CFG), recording detailed variable changes
- When one Block has completed its execution and is about to move to another Block, please determine based on the CFG which Block should be executed next.
- For control flow statements (if/while/for), clearly record condition evaluation results
- Format: "Step i Block n: code_content -> variable_state_changes"

**Step 2: Verify execution results**
- After completing the execution trace, compare the final output with expected output
- If outputs match exactly: "✅ Test passed"
- If outputs don't match: "❌ Test failed: actual=[actual_result] vs expected=[expected_result]"

**Step 3: Error analysis (when verification fails)**
- Identify the specific code lines where errors occurred
- Analyze the root cause: logic errors, condition errors, variable assignment errors, etc.
- Reference the task description to understand what the code should do vs what it actually does
- Provide specific suggestions for fixing the identified issues

After analyzing ALL test cases, synthesize the findings to provide a final corrected code.
When you provide the corrected code, you should not only consider the 3 steps above, but also consider the task description.

### JSON Output Format
Please output strictly in the following JSON format:
{{
    "analysis_results": [
        {{
            "testcase_id": 1,
            "input_description": "Description of test case 1 input",
            "expected_output": "Expected output result", 
            "step1_execution_trace": {{
                "reasoning": "Detailed reasoning process for step-by-step execution",
                "execution_steps": [
                    "Step 1 Block i: code_content -> variable_state",
                    "Step 2 Block j: code_content -> variable_state",
                    "..."
                ],
                "final_output": "Final output"
            }},
            "step2_verification": {{
                "status": "Test passed" or "Test failed",
                "actual_output": "Actual execution result", 
                "comparison": "Detailed comparison explanation"
            }},
            "step3_error_analysis": {{
                "has_error": true/false,
                "error_blocks": ["block numbers with errors"],
                "error_type": "error type",
                "root_cause": "Detailed explanation of the root cause",
                "fix_suggestion": "Specific fix suggestion"
            }}
        }}
    ],
    "overall_analysis": {{
        "common_patterns": "Common error patterns across test cases",
        "bug_classification": "Bug classification",
        "fix_strategy": "Overall fix strategy"
    }},
    "corrected_code": "Complete corrected code",
    "explanation": "Detailed explanation of the changes made"
}}

### Quality Requirements
1. **Execution Trace Accuracy**: Strictly follow code logic and show realistic variable state changes. Make sure follow the CFG Block by Block when executing the code. DO NOT rely on the test cases and task description when executing the code.
2. **Error Analysis Depth**: Provide specific, actionable error analysis.
3. **Code Quality**: Ensure the corrected code passes all test cases. Ensure the corrected code does not have any syntax errors. Ensure the import statements are included and correct for all used modules and functions. 
4. **Reasoning Clarity**: Show clear logical reasoning throughout the analysis.
5. **JSON Compliance**: Maintain proper JSON structure.

Begin your systematic analysis now.

IMPORTANT: Keep your total response under token limit to avoid truncation. If the response is too long, you can appropriately omit the execution trace. Remember keep the response json format.
"""

    messages = [
        {'role': 'system', 'content': "You are an expert Python programmer specializing in systematic debugging using Chain-of-Thought reasoning."},
        {'role': 'user', 'content': prompt}
    ]

    try:
        response = get_completion_with_retry(messages)
        logger.info(f"selfdebug response: {response}")
        
        # 验证JSON格式
        try:
            json.loads(response)
            return response
        except json.JSONDecodeError as e:
            logger.error("="*50)
            logger.error("chat_selfdebug中JSON解析失败！详细信息如下：")
            logger.error(f"JSON错误详情: {str(e)}")
            logger.error(f"响应总长度: {len(response) if response else 0} 字符")
            logger.error(f"响应内容前500字符: {response[:500] if response else 'None'}...")
            logger.error(f"响应内容后100字符: {response[-100:] if response and len(response) > 100 else 'N/A'}...")
            logger.error("="*50)
            # 返回一个错误的JSON结构
            error_response = {
                "analysis_results": [],
                "overall_analysis": {
                    "common_patterns": "JSON parsing failed",
                    "bug_classification": "system_error",
                    "fix_strategy": "Unable to analyze"
                },
                "corrected_code": buggy_code,
                "explanation": f"JSON parsing error, returning original code: {str(e)}",
                "error": str(e)
            }
            return json.dumps(error_response, indent=2, ensure_ascii=False)
            
    except Exception as e:
        logger.error(f"selfdebug error: {e}")
        # 返回错误的JSON结构
        error_response = {
            "analysis_results": [],
            "overall_analysis": {
                "common_patterns": "System error",
                "bug_classification": "system_error", 
                "fix_strategy": "Unable to analyze"
            },
            "corrected_code": buggy_code,
            "explanation": f"Debugging process error, returning original code: {str(e)}",
            "error": str(e)
        }
        return json.dumps(error_response, indent=2, ensure_ascii=False)
