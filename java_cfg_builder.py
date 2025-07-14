import subprocess
import sys
import json
import tempfile
import os
from pathlib import Path
from loguru import logger
from typing import Dict, List, Set, Optional, Tuple, Any
import copy


class JavaCFG:
    def __init__(self, source_path: str, target_method: str = None, target_class: str = None):
        """
        Java函数级CFG构建器 - 支持Java语句类型，一行一个block
        Args:
            source_path: Java源代码文件路径
            target_method: 目标方法名（不包含参数），如果不指定则使用第一个方法
            target_class: 目标类名，如果不指定则使用第一个类
        """
        self.source_path = source_path
        self.source_code = Path(source_path).read_text(encoding='utf-8')
        self.source_lines = self.source_code.splitlines()
        
        # 解析Java AST
        self.java_ast = self._parse_java_ast()
        
        # 解析所有类和方法
        self.all_classes = self._parse_all_classes()
        self.all_methods = self._parse_all_methods()
        
        # 确定目标类和方法
        if target_class:
            if target_class not in self.all_classes:
                raise ValueError(f"目标类 '{target_class}' 在源代码中未找到")
            self.target_class = target_class
        else:
            self.target_class = list(self.all_classes.keys())[0] if self.all_classes else None
            
        if target_method:
            if target_method not in self.all_methods:
                raise ValueError(f"目标方法 '{target_method}' 在源代码中未找到")
            self.target_method = target_method
        else:
            # 从目标类中选择第一个方法
            class_methods = [method for method in self.all_methods.keys() 
                           if self.all_methods[method]['class'] == self.target_class]
            self.target_method = class_methods[0] if class_methods else None
            
        if not self.target_method:
            raise ValueError("未找到任何方法定义")
            
        logger.info(f"目标类: {self.target_class}")
        logger.info(f"目标方法: {self.target_method}")
        
        # 构建CFG
        self.blocks = []
        self.connections = []
        self.method_signature = self._get_method_signature(self.target_method)
        
        # 跟踪当前的循环和异常处理上下文
        self.loop_stack = []  # 用于处理break/continue
        self.try_stack = []   # 用于处理异常
        
        # 构建完整的CFG
        self._build_complete_cfg()
        
        # 生成文本表示
        self.cfg_text = self._generate_cfg_text()
        self.block_num = len(self.blocks)
        self.block_code_list = [block['code'] for block in self.blocks]
    
    def _parse_java_ast(self) -> Dict:
        """使用JavaParser解析Java代码"""
        try:
            # 创建临时Java文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False) as f:
                f.write(self.source_code)
                temp_java_file = f.name
            
            # 使用JavaParser解析（需要安装JavaParser的Python绑定）
            # 这里我们使用一个简化的方法，通过外部Java程序来解析
            ast_data = self._parse_with_external_parser(temp_java_file)
            
            # 清理临时文件
            os.unlink(temp_java_file)
            
            return ast_data
        except Exception as e:
            logger.error(f"Java AST解析失败: {e}")
            return self._fallback_parse()
    
    def _parse_with_external_parser(self, java_file: str) -> Dict:
        """使用外部JavaParser解析Java文件"""
        # 这里需要一个Java程序来解析AST并输出JSON
        # 为了简化，我们使用正则表达式进行基本解析
        return self._fallback_parse()
    
    def _fallback_parse(self) -> Dict:
        """回退的简单解析方法，使用正则表达式"""
        import re
        
        # 简单解析类和方法
        classes = {}
        methods = {}
        
        # 解析类定义
        class_pattern = r'(?:public\s+)?(?:abstract\s+)?class\s+(\w+)'
        for match in re.finditer(class_pattern, self.source_code):
            class_name = match.group(1)
            classes[class_name] = {
                'name': class_name,
                'start_line': self.source_code[:match.start()].count('\n') + 1
            }
        
        # 解析方法定义
        method_pattern = r'(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:\w+\s+)*(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{'
        for match in re.finditer(method_pattern, self.source_code):
            method_name = match.group(1)
            if method_name not in ['if', 'while', 'for', 'switch']:  # 排除关键字
                # 找到方法所属的类
                method_line = self.source_code[:match.start()].count('\n') + 1
                belonging_class = None
                for class_name, class_info in classes.items():
                    if method_line > class_info['start_line']:
                        belonging_class = class_name
                
                methods[method_name] = {
                    'name': method_name,
                    'class': belonging_class,
                    'start_line': method_line,
                    'body_start': match.end()
                }
        
        return {
            'classes': classes,
            'methods': methods,
            'source_lines': self.source_lines
        }
    
    def _parse_all_classes(self) -> Dict[str, Dict]:
        """解析所有类定义"""
        return self.java_ast.get('classes', {})
    
    def _parse_all_methods(self) -> Dict[str, Dict]:
        """解析所有方法定义"""
        return self.java_ast.get('methods', {})
    
    def _get_method_signature(self, method_name: str) -> str:
        """获取带参数的方法签名"""
        if method_name in self.all_methods:
            method_info = self.all_methods[method_name]
            class_name = method_info.get('class', '')
            return f"{class_name}.{method_name}()"
        return f"{method_name}()"
    
    def _build_complete_cfg(self):
        """构建完整的CFG"""
        visited_methods = set()
        self._build_method_cfg(self.target_method, visited_methods)
    
    def _build_method_cfg(self, method_name: str, visited_methods: Set[str]):
        """递归构建方法的CFG"""
        if method_name in visited_methods:
            logger.warning(f"检测到递归调用: {method_name}")
            return
            
        if method_name not in self.all_methods:
            logger.warning(f"方法 {method_name} 未找到定义，跳过")
            return
            
        visited_methods.add(method_name)
        method_info = self.all_methods[method_name]
        
        logger.info(f"处理方法: {method_name}")
        
        # 解析方法体
        method_body = self._extract_method_body(method_info)
        main_blocks = self._process_java_statements(method_body, visited_methods, method_name)
        
        # 处理方法调用
        self._process_method_calls_in_blocks(visited_methods)
        
        visited_methods.remove(method_name)
    
    def _extract_method_body(self, method_info: Dict) -> List[str]:
        """提取方法体的语句"""
        start_line = method_info['start_line']
        
        # 找到方法体的开始和结束
        lines = []
        brace_count = 0
        in_method_body = False
        
        for i, line in enumerate(self.source_lines[start_line - 1:], start=start_line):
            stripped = line.strip()
            if not in_method_body and '{' in line:
                in_method_body = True
                brace_count += line.count('{') - line.count('}')
                # 如果开始行有代码，也要包含
                if stripped.replace('{', '').strip():
                    lines.append(line)
                continue
            
            if in_method_body:
                brace_count += line.count('{') - line.count('}')
                if brace_count > 0:
                    lines.append(line)
                else:
                    # 方法结束
                    break
        
        return lines
    
    def _process_java_statements(self, statements: List[str], visited_methods: Set[str], method_name: str) -> List[int]:
        """处理Java语句列表"""
        block_ids = []
        
        i = 0
        while i < len(statements):
            stmt = statements[i].strip()
            if not stmt or stmt.startswith('//') or stmt.startswith('/*'):
                i += 1
                continue
            
            # 根据语句类型处理
            stmt_blocks, consumed_lines = self._process_single_java_statement(
                statements[i:], visited_methods, method_name, i + 1)
            block_ids.extend(stmt_blocks)
            i += consumed_lines
        
        # 建立顺序连接
        self._connect_sequential_blocks(block_ids)
        
        # 添加控制结构连接
        self._add_java_control_structure_connections()
        
        return block_ids
    
    def _process_single_java_statement(self, statements: List[str], visited_methods: Set[str], 
                                     method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理单个Java语句"""
        stmt = statements[0].strip()
        
        # if语句
        if stmt.startswith('if'):
            return self._process_java_if(statements, visited_methods, method_name, line_number)
        # for循环
        elif stmt.startswith('for'):
            return self._process_java_for(statements, visited_methods, method_name, line_number)
        # while循环
        elif stmt.startswith('while'):
            return self._process_java_while(statements, visited_methods, method_name, line_number)
        # do-while循环
        elif stmt.startswith('do'):
            return self._process_java_do_while(statements, visited_methods, method_name, line_number)
        # switch语句
        elif stmt.startswith('switch'):
            return self._process_java_switch(statements, visited_methods, method_name, line_number)
        # try-catch语句
        elif stmt.startswith('try'):
            return self._process_java_try(statements, visited_methods, method_name, line_number)
        # return语句
        elif stmt.startswith('return'):
            return self._process_java_return(statements, visited_methods, method_name, line_number)
        # break语句
        elif stmt.startswith('break'):
            return self._process_java_break(stmt, method_name, line_number)
        # continue语句
        elif stmt.startswith('continue'):
            return self._process_java_continue(stmt, method_name, line_number)
        # throw语句
        elif stmt.startswith('throw'):
            return self._process_java_throw(stmt, method_name, line_number)
        # 变量声明或赋值
        else:
            return self._process_java_assignment(stmt, visited_methods, method_name, line_number)
    
    def _process_java_if(self, statements: List[str], visited_methods: Set[str], 
                        method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java if语句"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析if条件
        if_line = statements[0].strip()
        condition = self._extract_condition(if_line)
        
        # 创建if块
        if_block_id = self._create_java_block(if_line, 'if_statement', method_name, line_number, {
            'condition': condition
        })
        all_blocks.append(if_block_id)
        consumed_lines += 1
        
        # 处理if体
        then_statements, then_consumed = self._extract_block_statements(statements[1:])
        then_blocks = self._process_java_statements(then_statements, visited_methods, method_name)
        all_blocks.extend(then_blocks)
        consumed_lines += then_consumed
        
        # 检查是否有else
        else_blocks = []
        if (consumed_lines < len(statements) and 
            statements[consumed_lines].strip().startswith('else')):
            else_line = statements[consumed_lines].strip()
            consumed_lines += 1
            
            if else_line.startswith('else if'):
                # else if情况，递归处理
                else_if_blocks, else_if_consumed = self._process_java_if(
                    statements[consumed_lines-1:], visited_methods, method_name, line_number + consumed_lines)
                else_blocks.extend(else_if_blocks)
                consumed_lines += else_if_consumed - 1
            else:
                # 纯else情况
                else_statements, else_consumed = self._extract_block_statements(statements[consumed_lines:])
                else_blocks = self._process_java_statements(else_statements, visited_methods, method_name)
                all_blocks.extend(else_blocks)
                consumed_lines += else_consumed
        
        # 建立连接
        self._connect_java_if_statement(if_block_id, then_blocks, else_blocks, condition)
        
        return all_blocks, consumed_lines
    
    def _process_java_for(self, statements: List[str], visited_methods: Set[str], 
                         method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java for循环"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析for语句
        for_line = statements[0].strip()
        condition = self._extract_condition(for_line)
        
        # 创建for块
        for_block_id = self._create_java_block(for_line, 'for_statement', method_name, line_number, {
            'condition': condition
        })
        all_blocks.append(for_block_id)
        consumed_lines += 1
        
        # 将for循环推入栈
        self.loop_stack.append({
            'type': 'for',
            'header_id': for_block_id,
            'line': for_line
        })
        
        # 处理循环体
        body_statements, body_consumed = self._extract_block_statements(statements[1:])
        body_blocks = self._process_java_statements(body_statements, visited_methods, method_name)
        all_blocks.extend(body_blocks)
        consumed_lines += body_consumed
        
        # 弹出循环栈
        self.loop_stack.pop()
        
        # 建立连接
        self._connect_java_for_loop(for_block_id, body_blocks, condition)
        
        return all_blocks, consumed_lines
    
    def _process_java_while(self, statements: List[str], visited_methods: Set[str], 
                           method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java while循环"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析while语句
        while_line = statements[0].strip()
        condition = self._extract_condition(while_line)
        
        # 创建while块
        while_block_id = self._create_java_block(while_line, 'while_statement', method_name, line_number, {
            'condition': condition
        })
        all_blocks.append(while_block_id)
        consumed_lines += 1
        
        # 将while循环推入栈
        self.loop_stack.append({
            'type': 'while',
            'header_id': while_block_id,
            'line': while_line
        })
        
        # 处理循环体
        body_statements, body_consumed = self._extract_block_statements(statements[1:])
        body_blocks = self._process_java_statements(body_statements, visited_methods, method_name)
        all_blocks.extend(body_blocks)
        consumed_lines += body_consumed
        
        # 弹出循环栈
        self.loop_stack.pop()
        
        # 建立连接
        self._connect_java_while_loop(while_block_id, body_blocks, condition)
        
        return all_blocks, consumed_lines
    
    def _process_java_do_while(self, statements: List[str], visited_methods: Set[str], 
                              method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java do-while循环"""
        all_blocks = []
        consumed_lines = 0
        
        # 创建do块
        do_line = statements[0].strip()
        do_block_id = self._create_java_block(do_line, 'do_statement', method_name, line_number)
        all_blocks.append(do_block_id)
        consumed_lines += 1
        
        # 处理do体
        body_statements, body_consumed = self._extract_block_statements(statements[1:])
        body_blocks = self._process_java_statements(body_statements, visited_methods, method_name)
        all_blocks.extend(body_blocks)
        consumed_lines += body_consumed
        
        # 处理while条件
        while_line = statements[consumed_lines].strip()
        condition = self._extract_condition(while_line)
        while_block_id = self._create_java_block(while_line, 'while_condition', method_name, 
                                                line_number + consumed_lines, {'condition': condition})
        all_blocks.append(while_block_id)
        consumed_lines += 1
        
        # 建立连接
        self._connect_java_do_while_loop(do_block_id, body_blocks, while_block_id, condition)
        
        return all_blocks, consumed_lines
    
    def _process_java_switch(self, statements: List[str], visited_methods: Set[str], 
                            method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java switch语句"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析switch语句
        switch_line = statements[0].strip()
        condition = self._extract_condition(switch_line)
        
        # 创建switch块
        switch_block_id = self._create_java_block(switch_line, 'switch_statement', method_name, line_number, {
            'condition': condition
        })
        all_blocks.append(switch_block_id)
        consumed_lines += 1
        
        # 解析case和default块
        case_blocks = []
        i = 1
        while i < len(statements):
            line = statements[i].strip()
            if line.startswith('case') or line.startswith('default'):
                # 创建case/default块
                case_block_id = self._create_java_block(line, 'case_statement', method_name, 
                                                       line_number + i)
                all_blocks.append(case_block_id)
                case_blocks.append((case_block_id, line))
                consumed_lines += 1
                i += 1
                
                # 处理case体
                case_statements = []
                while i < len(statements) and not statements[i].strip().startswith(('case', 'default', '}')):
                    case_statements.append(statements[i])
                    i += 1
                
                if case_statements:
                    case_body_blocks = self._process_java_statements(case_statements, visited_methods, method_name)
                    all_blocks.extend(case_body_blocks)
                    consumed_lines += len(case_statements)
            elif line == '}':
                consumed_lines += 1
                break
            else:
                i += 1
        
        # 建立连接
        self._connect_java_switch_statement(switch_block_id, case_blocks, condition)
        
        return all_blocks, consumed_lines
    
    def _process_java_try(self, statements: List[str], visited_methods: Set[str], 
                         method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java try-catch语句"""
        all_blocks = []
        consumed_lines = 0
        
        # 创建try块
        try_line = statements[0].strip()
        try_block_id = self._create_java_block(try_line, 'try_statement', method_name, line_number)
        all_blocks.append(try_block_id)
        consumed_lines += 1
        
        # 处理try体
        try_statements, try_consumed = self._extract_block_statements(statements[1:])
        try_blocks = self._process_java_statements(try_statements, visited_methods, method_name)
        all_blocks.extend(try_blocks)
        consumed_lines += try_consumed
        
        # 处理catch块
        catch_blocks = []
        while (consumed_lines < len(statements) and 
               statements[consumed_lines].strip().startswith('catch')):
            catch_line = statements[consumed_lines].strip()
            catch_block_id = self._create_java_block(catch_line, 'catch_statement', method_name, 
                                                    line_number + consumed_lines)
            all_blocks.append(catch_block_id)
            consumed_lines += 1
            
            # 处理catch体
            catch_statements, catch_consumed = self._extract_block_statements(statements[consumed_lines:])
            catch_body_blocks = self._process_java_statements(catch_statements, visited_methods, method_name)
            all_blocks.extend(catch_body_blocks)
            catch_blocks.append([catch_block_id] + catch_body_blocks)
            consumed_lines += catch_consumed
        
        # 处理finally块
        finally_blocks = []
        if (consumed_lines < len(statements) and 
            statements[consumed_lines].strip().startswith('finally')):
            finally_line = statements[consumed_lines].strip()
            finally_block_id = self._create_java_block(finally_line, 'finally_statement', method_name, 
                                                      line_number + consumed_lines)
            all_blocks.append(finally_block_id)
            consumed_lines += 1
            
            # 处理finally体
            finally_statements, finally_consumed = self._extract_block_statements(statements[consumed_lines:])
            finally_body_blocks = self._process_java_statements(finally_statements, visited_methods, method_name)
            all_blocks.extend(finally_body_blocks)
            finally_blocks = [finally_block_id] + finally_body_blocks
            consumed_lines += finally_consumed
        
        # 建立连接
        self._connect_java_try_statement(try_blocks, catch_blocks, finally_blocks)
        
        return all_blocks, consumed_lines
    
    def _process_java_return(self, statements: List[str], visited_methods: Set[str], 
                            method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java return语句"""
        return_line = statements[0].strip()
        block_id = self._create_java_block(return_line, 'return', method_name, line_number)
        return [block_id], 1
    
    def _process_java_break(self, stmt: str, method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java break语句"""
        block_id = self._create_java_block(stmt, 'break', method_name, line_number)
        
        # 连接到最近的循环外部
        if self.loop_stack:
            current_loop = self.loop_stack[-1]
            self.blocks[block_id]['break_target'] = current_loop
        
        return [block_id], 1
    
    def _process_java_continue(self, stmt: str, method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java continue语句"""
        block_id = self._create_java_block(stmt, 'continue', method_name, line_number)
        
        # 连接到最近的循环头部
        if self.loop_stack:
            current_loop = self.loop_stack[-1]
            self._add_connection(block_id, current_loop['header_id'], 'continue')
        
        return [block_id], 1
    
    def _process_java_throw(self, stmt: str, method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java throw语句"""
        block_id = self._create_java_block(stmt, 'throw', method_name, line_number)
        return [block_id], 1
    
    def _process_java_assignment(self, stmt: str, visited_methods: Set[str], 
                                method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java赋值或表达式语句"""
        # 检测语句类型
        if '=' in stmt and not any(op in stmt for op in ['==', '!=', '<=', '>=']):
            block_type = 'assignment'
        else:
            block_type = 'expression'
        
        block_id = self._create_java_block(stmt, block_type, method_name, line_number)
        return [block_id], 1
    
    def _create_java_block(self, code: str, block_type: str, method_name: str, 
                          line_number: int, extra_info: Dict = None) -> int:
        """创建一个新的Java block"""
        block_id = len(self.blocks)
        
        block_info = {
            'id': block_id,
            'type': block_type,
            'code': code,
            'line_number': line_number,
            'method': method_name,
            'method_calls': self._extract_java_method_calls(code)
        }
        
        if extra_info:
            block_info.update(extra_info)
            
        self.blocks.append(block_info)
        
        return block_id
    
    def _extract_condition(self, line: str) -> str:
        """提取条件表达式"""
        import re
        
        # 匹配括号内的条件
        match = re.search(r'\(([^)]+)\)', line)
        if match:
            return match.group(1)
        return ""
    
    def _extract_block_statements(self, statements: List[str]) -> Tuple[List[str], int]:
        """提取块语句（处理大括号）"""
        block_statements = []
        consumed_lines = 0
        brace_count = 0
        
        for i, line in enumerate(statements):
            stripped = line.strip()
            
            # 计算大括号
            brace_count += line.count('{') - line.count('}')
            
            if stripped == '{':
                consumed_lines += 1
                continue
            elif stripped == '}' and brace_count == 0:
                consumed_lines += 1
                break
            elif brace_count > 0:
                block_statements.append(line)
                consumed_lines += 1
            elif brace_count == 0 and i == 0:
                # 单行语句（没有大括号）
                block_statements.append(line)
                consumed_lines += 1
                break
        
        return block_statements, consumed_lines
    
    def _extract_java_method_calls(self, code: str) -> List[str]:
        """提取Java代码中的方法调用"""
        import re
        method_calls = []
        
        # 匹配方法调用模式 methodName(...)
        pattern = r'(\w+)\s*\('
        matches = re.findall(pattern, code)
        
        for match in matches:
            if match in self.all_methods:
                method_calls.append(match)
        
        return list(set(method_calls))  # 去重
    
    def _add_connection(self, from_block: int, to_block: int, connection_type: str):
        """添加块之间的连接"""
        # 检查是否已经存在相同的连接，避免重复
        for existing_conn in self.connections:
            if (existing_conn['from'] == from_block and 
                existing_conn['to'] == to_block and 
                existing_conn['type'] == connection_type):
                return  # 连接已存在，不重复添加
        
        self.connections.append({
            'from': from_block,
            'to': to_block,
            'type': connection_type
        })
    
    def _connect_sequential_blocks(self, block_ids: List[int]):
        """建立顺序块之间的连接"""
        for i in range(len(block_ids) - 1):
            current_block = self.blocks[block_ids[i]]
            next_block = self.blocks[block_ids[i + 1]]
            
            # 跳过控制结构块和不应该有顺序连接的块
            if current_block['type'] not in ['return', 'break', 'continue', 'throw', 
                                           'for_statement', 'while_statement', 'if_statement', 
                                           'switch_statement', 'case_statement']:
                self._add_connection(block_ids[i], block_ids[i + 1], 'sequential')
    
    def _connect_java_if_statement(self, if_block_id: int, then_blocks: List[int], 
                                  else_blocks: List[int], condition: str):
        """建立Java if语句的连接"""
        # if -> then分支
        if then_blocks:
            self._add_connection(if_block_id, then_blocks[0], f'condition_true:{condition}')
        
        # if -> else分支
        if else_blocks:
            self._add_connection(if_block_id, else_blocks[0], f'condition_false:{condition}')
    
    def _connect_java_for_loop(self, for_block_id: int, body_blocks: List[int], condition: str):
        """建立Java for循环的连接"""
        # for -> 循环体
        if body_blocks:
            self._add_connection(for_block_id, body_blocks[0], f'condition_true:{condition}')
            
            # 循环体最后的块 -> for头（循环回去）
            for block_id in body_blocks:
                block = self.blocks[block_id]
                if block['type'] not in ['return', 'break', 'continue', 'throw']:
                    self._add_connection(block_id, for_block_id, 'loop_back')
    
    def _connect_java_while_loop(self, while_block_id: int, body_blocks: List[int], condition: str):
        """建立Java while循环的连接"""
        # while -> 循环体
        if body_blocks:
            self._add_connection(while_block_id, body_blocks[0], f'condition_true:{condition}')
            
            # 循环体最后的块 -> while头（循环回去）
            for block_id in body_blocks:
                block = self.blocks[block_id]
                if block['type'] not in ['return', 'break', 'continue', 'throw']:
                    self._add_connection(block_id, while_block_id, 'loop_back')
    
    def _connect_java_do_while_loop(self, do_block_id: int, body_blocks: List[int], 
                                   while_block_id: int, condition: str):
        """建立Java do-while循环的连接"""
        # do -> 循环体
        if body_blocks:
            self._add_connection(do_block_id, body_blocks[0], 'sequential')
            
            # 循环体 -> while条件
            last_body_block = body_blocks[-1] if body_blocks else do_block_id
            self._add_connection(last_body_block, while_block_id, 'sequential')
            
            # while条件为真 -> do头（循环回去）
            self._add_connection(while_block_id, do_block_id, f'condition_true:{condition}')
    
    def _connect_java_switch_statement(self, switch_block_id: int, case_blocks: List[Tuple[int, str]], condition: str):
        """建立Java switch语句的连接"""
        for case_block_id, case_line in case_blocks:
            if case_line.startswith('case'):
                case_value = case_line.split()[1].rstrip(':')
                self._add_connection(switch_block_id, case_block_id, f'case_match:{case_value}')
            elif case_line.startswith('default'):
                self._add_connection(switch_block_id, case_block_id, 'default_case')
    
    def _connect_java_try_statement(self, try_blocks: List[int], catch_blocks: List[List[int]], 
                                   finally_blocks: List[int]):
        """建立Java try-catch语句的连接"""
        # try块到catch块的连接（异常发生时）
        for try_block_id in try_blocks:
            for catch_block_list in catch_blocks:
                if catch_block_list:
                    self._add_connection(try_block_id, catch_block_list[0], 'exception')
        
        # 到finally块的连接
        if finally_blocks:
            # try块正常完成时到finally
            if try_blocks:
                last_try_block = try_blocks[-1]
                self._add_connection(last_try_block, finally_blocks[0], 'finally')
            
            # catch块完成时到finally
            for catch_block_list in catch_blocks:
                if catch_block_list:
                    last_catch_block = catch_block_list[-1]
                    self._add_connection(last_catch_block, finally_blocks[0], 'finally')
    
    def _add_java_control_structure_connections(self):
        """添加Java控制结构的额外连接"""
        # 处理break语句的跳出连接
        for block in self.blocks:
            if block['type'] == 'break' and 'break_target' in block:
                # 找到循环外的下一个语句
                loop_info = block['break_target']
                exit_target = self._find_loop_exit_target(loop_info)
                if exit_target is not None:
                    self._add_connection(block['id'], exit_target, 'break_exit')
        
        # 处理方法调用连接
        self._add_java_method_call_connections()
    
    def _find_loop_exit_target(self, loop_info: Dict) -> Optional[int]:
        """找到循环的退出目标"""
        # 简化实现：找到循环后的第一个块
        loop_line = loop_info.get('line', '')
        if not loop_line:
            return None
        
        # 找到循环行号后的第一个非循环块
        for block in self.blocks:
            if (block['line_number'] > loop_info.get('header_id', 0) and
                block['type'] not in ['break', 'continue']):
                return block['id']
        
        return None
    
    def _add_java_method_call_connections(self):
        """添加Java方法调用连接"""
        for block in self.blocks:
            if block.get('method_calls'):
                for method_call in block['method_calls']:
                    if method_call in self.all_methods:
                        # 找到被调用方法的第一个块
                        method_first_block = self._find_method_first_block(method_call)
                        if method_first_block is not None:
                            self._add_connection(block['id'], method_first_block, 'method_call')
                        
                        # 找到被调用方法的返回块
                        method_return_blocks = self._find_method_return_blocks(method_call)
                        for return_block in method_return_blocks:
                            self._add_connection(return_block, block['id'], 'method_return')
    
    def _find_method_first_block(self, method_name: str) -> Optional[int]:
        """找到方法的第一个块"""
        for block in self.blocks:
            if block['method'] == method_name:
                return block['id']
        return None
    
    def _find_method_return_blocks(self, method_name: str) -> List[int]:
        """找到方法的所有返回块"""
        return_blocks = []
        for block in self.blocks:
            if (block['method'] == method_name and 
                block['type'] == 'return'):
                return_blocks.append(block['id'])
        return return_blocks
    
    def _process_method_calls_in_blocks(self, visited_methods: Set[str]):
        """处理所有块中的方法调用"""
        methods_to_process = set()
        for block in self.blocks:
            if block.get('method_calls'):
                for method_call in block['method_calls']:
                    if method_call in self.all_methods and method_call not in visited_methods:
                        methods_to_process.add(method_call)
        
        # 处理每个方法调用
        for method_call in methods_to_process:
            logger.info(f"发现方法调用: {method_call}")
            self._build_method_cfg(method_call, visited_methods.copy())
    
    def _generate_cfg_text(self) -> str:
        """生成CFG的文本表示"""
        header = f"G describes a control flow graph of Method `{self.method_signature}`\nIn this graph:"
        
        # 找到主方法的第一个执行块作为起点
        entry_block_id = self._find_main_method_entry_block()
        end_block_id = len(self.blocks)
        
        # 专门说明Entry Point和END Block
        entry_info = []
        if entry_block_id is not None:
            entry_block = self.blocks[entry_block_id]
            entry_code = entry_block['code'].replace('\n', '\\n')
            entry_info.append(f"Entry Point: Block {entry_block_id} represents code snippet: {entry_code}.")
        entry_info.append(f"END Block: Block {end_block_id} represents code snippet: END.")
        
        # 生成块描述
        block_descriptions = []
        for block in self.blocks:
            code = block['code'].replace('\n', '\\n')
            block_descriptions.append(f"Block {block['id']} represents code snippet: {code}.")
        
        # 添加统一的END标记
        block_descriptions.append(f"Block {end_block_id} represents code snippet: END.")
        
        # 生成连接描述
        edge_descriptions = []
        sorted_connections = sorted(self.connections, key=lambda x: (x['from'], x['to']))
        
        # 去重处理
        seen_connections = set()
        unique_connections = []
        for conn in sorted_connections:
            conn_key = (conn['from'], conn['to'], conn['type'])
            if conn_key not in seen_connections:
                seen_connections.add(conn_key)
                unique_connections.append(conn)
        
        for conn in unique_connections:
            conn_type = conn['type']
            
            if conn_type == 'sequential':
                edge_descriptions.append(f"Block {conn['from']} unconditional points to Block {conn['to']}.")
            elif conn_type == 'loop_back':
                edge_descriptions.append(f"Block {conn['from']} loop back to Block {conn['to']}.")
            elif conn_type == 'continue':
                edge_descriptions.append(f"Block {conn['from']} continue points to Block {conn['to']}.")
            elif conn_type == 'break_exit':
                edge_descriptions.append(f"Block {conn['from']} break exit points to Block {conn['to']}.")
            elif conn_type == 'method_call':
                edge_descriptions.append(f"Block {conn['from']} method call points to Block {conn['to']}.")
            elif conn_type == 'method_return':
                edge_descriptions.append(f"Block {conn['from']} method return points to Block {conn['to']}.")
            elif conn_type.startswith('condition_true:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('condition_false:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} not match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('case_match:'):
                case_value = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} case match \"{case_value}\" points to Block {conn['to']}.")
            elif conn_type == 'default_case':
                edge_descriptions.append(f"Block {conn['from']} default case points to Block {conn['to']}.")
            elif conn_type == 'exception':
                edge_descriptions.append(f"Block {conn['from']} exception points to Block {conn['to']}.")
            elif conn_type == 'finally':
                edge_descriptions.append(f"Block {conn['from']} finally points to Block {conn['to']}.")
            else:
                edge_descriptions.append(f"Block {conn['from']} {conn_type} points to Block {conn['to']}.")
        
        # 为主方法的return语句添加到END的连接
        for block in self.blocks:
            if (block['type'] == 'return' and 
                block['method'] == self.target_method):
                edge_descriptions.append(f"Block {block['id']} unconditional points to Block {end_block_id}.")
        
        # 组合所有部分
        body_parts = entry_info + block_descriptions + edge_descriptions
        body = "\n".join(body_parts)
        return f"{header}\n{body}"
    
    def _find_main_method_entry_block(self) -> Optional[int]:
        """找到主方法的第一个执行块（入口点）"""
        for block in self.blocks:
            if block['method'] == self.target_method:
                return block['id']
        return None
    
    def print_features(self):
        """打印CFG特征信息"""
        logger.info("=================Java Method CFG=================")
        logger.info(f"目标类: {self.target_class}")
        logger.info(f"目标方法: {self.target_method}")
        logger.info(f"方法签名: {self.method_signature}")
        logger.info(f"所有类: {list(self.all_classes.keys())}")
        logger.info(f"所有方法: {list(self.all_methods.keys())}")
        logger.info(f"块数量: {self.block_num}")
        logger.info(f"连接数量: {len(self.connections)}")
        
        logger.info("块信息:")
        for block in self.blocks:
            logger.info(f"  Block {block['id']} ({block['type']}): {block['code'][:50]}...")
        
        logger.info("连接信息:")
        for conn in self.connections:
            logger.info(f"  {conn['from']} --{conn['type']}--> {conn['to']}")
        
        logger.info(f"CFG文本表示:\n{self.cfg_text}")
        logger.info("=================Java Method CFG=================")


# 测试函数
def test_java_cfg():
    """测试Java CFG构建器"""
    test_code = '''
public class TestClass {
    
    public int helperMethod(int x) {
        if (x > 0) {
            return x * 2;
        } else {
            return x * -1;
        }
    }
    
    public int[] mainMethod(int[] arr) {
        int[] result = new int[arr.length];
        int index = 0;
        
        try {
            for (int i = 0; i < arr.length; i++) {
                if (arr[i] > 0) {
                    continue;
                } else if (arr[i] == 0) {
                    break;
                }
                
                int processed = helperMethod(arr[i]);
                result[index++] = processed;
            }
            
            while (index > 5) {
                index--;
            }
        } catch (Exception e) {
            System.out.println("Error occurred");
            result = new int[0];
        } finally {
            System.out.println("Processing completed");
        }
        
        return result;
    }
}
'''
    
    # 写入测试文件
    test_file = "TestClass.java"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)
    
    try:
        # 测试Java CFG构建器
        cfg = JavaCFG(test_file, "mainMethod", "TestClass")
        cfg.print_features()
        
        print(f"\n生成的块数量: {cfg.block_num}")
        print(f"生成的连接数量: {len(cfg.connections)}")
        
    finally:
        # 清理测试文件
        import os
        if os.path.exists(test_file):
            os.remove(test_file)


if __name__ == "__main__":
    test_java_cfg() 