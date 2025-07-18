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
- **功能**：构建Prompt，与大语言模型进行交互

#### 2. `complete_cfg_builder.py` - Python CFG构建器
- **功能**：为Python代码构建详细的控制流图，控制流图用文本形式表示

#### 3. `java_cfg_builder.py` - Java CFG构建器
- **功能**：为Python代码构建详细的控制流图，控制流图用文本形式表示

#### 4. `utils.py` - 工具函数库

#### 5. `self_debug_multi.py` - Python selfdebug流程示例
- **简介**：单个任务的调试演示
- **说明**：测试基本的CFG构建和代码修复流程（不包含检测流程）
- **使用方法**：
  ```bash
  python self_debug_multi.py
  ```
  会打印出task_id的修复后代码

#### 6. `self_debug_parallel.py` - Python selfdebug并行处理脚本
- **简介**：多线程并行处理humanevalfix数据集
- **说明**：
  - 对humanevalfix中所有数据进行代码修复
  - 使用隐藏的测例进行真实执行验证代码修复正确率
  - 结果保存在`dataset_test/humanevalfix/results`中
- **使用方法**：
  ```bash
  python self_debug_parallel.py
  ```
  
#### 11. `selfdebug_java_defects4j.py` - Java缺陷处理脚本
- **功能**：处理Defects4J数据集中的Java代码缺陷
- **特性**：
  - 支持Java代码的CFG构建
  - 集成defects4j验证工具
  - 支持限制处理数量（调试用）
- **使用方法**：
  ```bash
  # 处理所有缺陷
  python selfdebug_java_defects4j.py
  
  # 限制处理数量
  python selfdebug_java_defects4j.py --limit 10
  
  # 包含验证
  python selfdebug_java_defects4j.py --validate
  ```

#### 6. `self_debug_serial.py` - 串行处理脚本
- **功能**：串行处理HumanEval数据集
- **特性**：
  - 逐个处理数据集中的错误代码,获得修正后的代码
  - 将修正后的代码使用隐藏测试集真实执行，验证修复正确率
  - 结果保存在`dataset_test/humanevalfix/results`中
- **使用方法**：
  ```bash
  python self_debug_serial.py [start_index] [end_index]
  ```
### 消融实验相关文件
#### 多Agent→单Agent(一次对话)


#### 8. `self_debug_multi.py` - 多进程处理脚本
- **功能**：使用多进程并行处理大规模数据集
- **特性**：
  - 更好的CPU利用率
  - 进程间隔离，避免内存泄漏
  - 支持断点续传
- **使用方法**：
  ```bash
  python self_debug_multi.py --processes 8
  ```

#### 9. `self_debug_multi_parallel.py` - 混合并行脚本
- **功能**：结合多进程和多线程的混合并行处理
- **特性**：
  - 最大化系统资源利用
  - 适合大规模数据集处理
  - 智能负载分配

#### 10. `direct_fix_parallel.py` - 直接修复脚本
- **功能**：不使用CFG，直接调用LLM修复代码
- **用途**：对比实验，评估CFG的作用
- **使用方法**：
  ```bash
  python direct_fix_parallel.py --workers 4
  ```

### Java专用模块



### 辅助工具

#### 12. `filter_failed_tasks.py` - 失败任务筛选器
- **功能**：分析和筛选测试失败的任务
- **用途**：
  - 比较不同方法的失败模式
  - 生成失败任务报告
  - 支持结果分析

#### 13. `runtest.py` - 测试运行器
- **功能**：单独测试代码修复结果
- **用途**：验证修复后代码的正确性

#### 14. `view_and_validate_results.py` - 结果查看器
- **功能**：查看和验证实验结果
- **特性**：
  - 结果统计和可视化
  - 错误模式分析
  - 成功率计算

## 环境配置

### 1. 创建`.env`文件
```bash
GPT_API_KEY=your_openai_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

### 2. 安装依赖
```bash
pip install openai loguru python-dotenv tqdm
```

### 3. 数据集准备
- 将HumanEval数据集放在`data/humanevalfix/humanevalpack.jsonl`
- 将Defects4J数据集放在`dataset_test/SRepair/SRepair/dataset/defects4j-sf.json`

## 使用示例

### Python代码调试
```bash
# 串行处理（适合调试）
python self_debug_serial.py 1 10

# 并行处理（适合生产）
python self_debug_parallel.py --workers 4

# 多进程处理（适合大规模）
python self_debug_multi.py --processes 8
```

### Java代码调试
```bash
# 处理前5个Java缺陷
python selfdebug_java_defects4j.py --limit 5

# 处理并验证结果
python selfdebug_java_defects4j.py --validate
```

### 对比实验
```bash
# 使用CFG的方法
python self_debug_parallel.py --workers 4

# 不使用CFG的直接修复
python direct_fix_parallel.py --workers 4

# 比较结果
python filter_failed_tasks.py
```

## 输出文件

- `debug_results_*.json`: 详细的调试结果
- `debug_log_*.txt`: 处理日志
- `*_patches.json`: 生成的代码补丁
- `*_validation_results/`: 验证结果目录

## 性能调优

1. **并行度设置**：根据CPU核心数和API限制调整
2. **内存管理**：大数据集建议使用多进程模式
3. **API限制**：注意模型服务商的速率限制
4. **日志级别**：生产环境建议关闭详细日志

## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 发起 Pull Request

## 许可证

MIT License - 详见 LICENSE 文件