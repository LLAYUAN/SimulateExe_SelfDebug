# SimulateExe_SelfDebug - 基于模拟执行的自动代码调试系统

## 项目简介

SimulateExe_SelfDebug 是一个基于大语言模型模拟执行自动代码调试系统，分为函数级代码修复和仓库级代码修复两个框架。该系统可以自动检测和修复Python/Java代码中的错误，适用于日常代码、项目代码、编程竞赛题目的处理。

## 函数级代码修复系统架构

本系统采用控制流图(CFG)静态分析 + 大语言模型动态模拟执行的混合方法：
1. **静态分析**：构建代码的控制流图，提供程序执行路径信息
2. **LLM动态模拟执行**：按照CFG路径，使用testcase进行模拟执行，提高LLM对代码整体框架和运行细节的理解
3. **CoT**：使用CoT进行错误定位→错误分析→修正代码
4. **MultiAgent**：每一个testcase使用一个Agent进行模拟执行和分析，获得修正后的代码和修改建议，最后由一个Agent进行总结。

## 文件说明

### 核心模块

#### 1. `chat.py` - LLM交互
- **简介**：构建Prompt，与大语言模型进行交互

#### 2. `complete_cfg_builder.py` - Python CFG构建器
- **简介**：为Python代码构建详细的控制流图，控制流图用文本形式表示

#### 3. `java_cfg_builder.py` - Java CFG构建器
- **简介**：为Python代码构建详细的控制流图，控制流图用文本形式表示

#### 4. `utils.py` - 工具函数库

#### 5. `self_debug_multi.py` - Python selfdebug流程示例
- **简介**：单个任务的调试演示
- **说明**：测试基本的CFG构建和代码修复流程（不包含检测流程）
- **使用方法**：
  ```bash
  python self_debug_multi.py
  ```
  会打印出task_id的修复后代码

#### 6. `self_debug_multi_parallel.py` - Python selfdebug并行处理脚本
- **简介**：多线程并行处理humanevalfix数据集
- **说明**：
  - 对humanevalfix中所有数据进行代码修复
  - 使用隐藏的测例进行真实执行验证代码修复正确率
  - 结果保存在`dataset_test/humanevalfix/results`中
- **使用方法**：
  ```bash
  python self_debug_multi_parallel.py
  ```

#### 7. `self_debug_multi_defects4j.py` - Java缺陷处理脚本
- **简介**：处理Defects4J数据集中的函数级Java代码缺陷
- **说明**：
  - 对defects4j中函数级数据进行代码修复
  - 使用SRepair的validation函数验证修复正确率
  - 修复后的代码保存在`dataset_test/SRepair/results/sf/defects4j_static_analysis_patches.json`
  - validation结果保存在`dataset_test/SRepair/results/sf/defects4j_validation_results`
- **使用方法**：
  ```bash
  # 处理所有缺陷
  python self_debug_multi_defects4j.py
  
  # 限制处理数量
  python self_debug_multi_defects4j.py --limit 10
  
  # 包含验证
  python self_debug_multi_defects4j.py --validate
  ```
- **注意**：
  - 由于defects4j的函数级数据集是代码片段，函数定义不完整，所以无法按行模拟执行，因此直接传入CFG然后让LLM analyze step by step，并未严格模拟执行获得输出。

### 消融实验文件
#### 1. `self_debug_single_parallel.py` - Python selfdebug 单Agent并行处理脚本
- **简介**：
  - 单Agent并行处理HumanEval数据集，是`self_debug_multi_parallel.py`的消融实验，多Agent→单Agent(一次对话)
  - 结果保存在`dataset_test/humanevalfix/results`中

#### 2. `direct_fix_parallel.py` - 直接修复脚本
- **简介**：
  - baseline（暂时），直接将错误代码和测例给LLM进行debug，无任何特殊处理
  - 结果保存在`dataset_test/humanevalfix/results`中

### 其他文件
#### 1. `buggy_code.py`
- **简介**：临时存储正在debug的Python的代码

#### 2. `runtest.py` - 手动验证脚本
- **简介**：真实执行，验证修复后的代码是否正确
- **使用方法**：将`code_to_test`替换为修复后的代码，将i替换为humanevalfix数据集中的第i行

#### 3. `self_debug_single_serial.py` - Python selfdebug 单Agent串行处理脚本

#### 4. `self_debug_single.py` - Python selfdebug 单Agent流程示例
- **简介**：单个任务的调试演示
- **说明**：测试基本的CFG构建和代码修复流程（不包含检测流程）
- **使用方法**：
  ```bash
  python self_debug_single.py
  ```
  会打印出task_id的修复后代码

## 环境配置
### 1. 创建`.env`文件
```bash
GPT_API_KEY=your_openai_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

### 2. 安装相关依赖

### 3. 使用Defects4j需要配置docker
- 首先在SRepair目录下创建LLM4APR image
  ```bash
  docker build ./ --tag llm4apr
  ```
- 创建container并运行
  ```bash
  docker run -it --name llm4apr_ctn llm4apr
  ```

## 优化（TODO）
考虑加一层LLM将复杂语句展开为基本语句，以提高模拟执行准确度

## 仓库级代码修复系统架构（TODO）
采用CFG+任务分解+模拟执行+多Agent