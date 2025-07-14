import ast
from pathlib import Path
from py2cfg import CFGBuilder
from loguru import logger
from typing import Dict, List, Set, Optional, Tuple, Any
import copy


class TextCFG:
    def __init__(self, source_path: str, main_function: str = None):
        """
        完整的函数级CFG构建器 - 支持所有Python语句类型，一行一个block
        Args:
            source_path: 源代码文件路径
            main_function: 主函数名（不包含参数），如果不指定则使用第一个函数
        """
        self.source_path = source_path
        self.source_code = Path(source_path).read_text(encoding='utf-8')
        self.source_lines = self.source_code.splitlines()
        self.ast_tree = ast.parse(self.source_code)
        
        # 解析所有函数定义
        self.all_functions = self._parse_all_functions()
        
        # 确定主函数
        if main_function:
            if main_function not in self.all_functions:
                raise ValueError(f"主函数 '{main_function}' 在源代码中未找到")
            self.main_function = main_function
        else:
            self.main_function = list(self.all_functions.keys())[0] if self.all_functions else None
            
        if not self.main_function:
            raise ValueError("未找到任何函数定义")
            
        logger.info(f"主函数: {self.main_function}")
        
        # 构建CFG
        self.blocks = []
        self.connections = []
        self.funcname = self._get_funcname_with_args(self.main_function)
        
        # 跟踪当前的循环和异常处理上下文
        self.loop_stack = []  # 用于处理break/continue
        self.try_stack = []   # 用于处理异常
        
        # 构建完整的CFG
        self._build_complete_cfg()
        
        # 生成文本表示
        self.cfg_text = self._generate_cfg_text()
        self.block_num = len(self.blocks)
        self.block_code_list = [block['code'] for block in self.blocks]
        
    def _parse_all_functions(self) -> Dict[str, ast.FunctionDef]:
        """解析所有函数定义"""
        functions = {}
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = node
        return functions
    
    def _get_funcname_with_args(self, func_name: str) -> str:
        """获取带参数的函数名"""
        if func_name in self.all_functions:
            func_node = self.all_functions[func_name]
            arg_names = [arg.arg for arg in func_node.args.args]
            return f"{func_name}({', '.join(arg_names)})"
        return f"{func_name}()"
    
    def _build_complete_cfg(self):
        """构建完整的CFG"""
        visited_functions = set()
        self._build_function_cfg(self.main_function, visited_functions)
        
    def _build_function_cfg(self, func_name: str, visited_functions: Set[str]):
        """递归构建函数的CFG"""
        if func_name in visited_functions:
            logger.warning(f"检测到递归调用: {func_name}")
            return
            
        if func_name not in self.all_functions:
            logger.warning(f"函数 {func_name} 未找到定义，跳过")
            return
            
        visited_functions.add(func_name)
        func_node = self.all_functions[func_name]
        
        logger.info(f"处理函数: {func_name}")
        
        # 处理函数体 - 按行处理
        main_blocks = self._process_statements_line_by_line(func_node.body, visited_functions, func_name)
        
        # 处理函数调用
        self._process_function_calls_in_blocks(visited_functions)
        
        visited_functions.remove(func_name)
    
    def _process_statements_line_by_line(self, statements: List[ast.stmt], 
                                        visited_functions: Set[str], 
                                        func_name: str) -> List[int]:
        """按行处理语句，每行创建一个block"""
        block_ids = []
        
        for stmt in statements:
            stmt_blocks = self._process_single_statement(stmt, visited_functions, func_name)
            block_ids.extend(stmt_blocks)
        
        # 建立顺序连接（排除控制结构块）
        self._connect_sequential_blocks(block_ids)
        
        # 在这里添加控制结构到下一个语句的连接
        self._add_control_structure_exit_connections(statements, block_ids)
        
        return block_ids
    
    def _process_single_statement(self, stmt: ast.stmt, visited_functions: Set[str], 
                                 func_name: str) -> List[int]:
        """处理单个语句，支持所有Python语句类型"""
        
        if isinstance(stmt, ast.Assign):
            return self._process_assign(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.AnnAssign):
            return self._process_ann_assign(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.AugAssign):
            return self._process_aug_assign(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.For):
            return self._process_for_loop(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.While):
            return self._process_while_loop(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.If):
            return self._process_if_statement(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.Try):
            return self._process_try_statement(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.With):
            return self._process_with_statement(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.Return):
            return self._process_return(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.Break):
            return self._process_break(stmt, func_name)
        elif isinstance(stmt, ast.Continue):
            return self._process_continue(stmt, func_name)
        elif isinstance(stmt, ast.Pass):
            return self._process_pass(stmt, func_name)
        elif isinstance(stmt, ast.Assert):
            return self._process_assert(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.Raise):
            return self._process_raise(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.Delete):
            return self._process_delete(stmt, func_name)
        elif isinstance(stmt, ast.Expr):
            return self._process_expression(stmt, visited_functions, func_name)
        elif isinstance(stmt, ast.Import):
            return self._process_import(stmt, func_name)
        elif isinstance(stmt, ast.ImportFrom):
            return self._process_import_from(stmt, func_name)
        elif isinstance(stmt, ast.Global):
            return self._process_global(stmt, func_name)
        elif isinstance(stmt, ast.Nonlocal):
            return self._process_nonlocal(stmt, func_name)
        elif isinstance(stmt, ast.FunctionDef):
            return self._process_function_def(stmt, visited_functions, func_name)
        else:
            # 未知语句类型，作为普通语句处理
            return self._process_unknown_statement(stmt, visited_functions, func_name)
    
    def _create_block(self, stmt: ast.stmt, block_type: str, func_name: str, 
                     extra_info: Dict = None) -> int:
        """创建一个新的block"""
        block_id = len(self.blocks)
        
        # 获取代码文本 - 根据语句类型特殊处理
        code = self._get_block_code(stmt, block_type)
        
        block_info = {
            'id': block_id,
            'type': block_type,
            'code': code,
            'ast_node': stmt,
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': self._extract_function_calls(stmt)
        }
        
        if extra_info:
            block_info.update(extra_info)
            
        self.blocks.append(block_info)
        
        return block_id
    
    def _get_block_code(self, stmt: ast.stmt, block_type: str) -> str:
        """根据语句类型获取正确的代码文本"""
        # 对if语句特殊处理，只显示条件部分
        if isinstance(stmt, ast.If) and block_type == 'if_statement':
            return f"if {ast.unparse(stmt.test)}:"
        
        # 对其他语句类型，优先使用AST unparsing以获得准确的代码
        try:
            # 使用AST unparse获取精确的代码表示
            code = ast.unparse(stmt)
            
            # 如果代码包含换行，取第一行并清理
            if '\n' in code:
                code = code.split('\n')[0].strip()
                
            return code
        except:
            # 如果AST unparse失败，回退到源代码行
            if hasattr(stmt, 'lineno'):
                line_num = stmt.lineno
                if 1 <= line_num <= len(self.source_lines):
                    return self.source_lines[line_num - 1].strip()
            
            # 最后的回退
            return str(type(stmt).__name__)
    
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
    
    # 具体语句处理方法
    def _process_assign(self, stmt: ast.Assign, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理赋值语句"""
        block_id = self._create_block(stmt, 'assign', func_name)
        return [block_id]
    
    def _process_ann_assign(self, stmt: ast.AnnAssign, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理类型注解赋值"""
        block_id = self._create_block(stmt, 'ann_assign', func_name)
        return [block_id]
    
    def _process_aug_assign(self, stmt: ast.AugAssign, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理增强赋值 (+=, -=, etc.)"""
        block_id = self._create_block(stmt, 'aug_assign', func_name)
        return [block_id]
    
    def _process_for_loop(self, stmt: ast.For, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理for循环"""
        all_blocks = []
        
        # 1. for语句本身
        for_block_id = self._create_block(stmt, 'for_statement', func_name, {
            'condition': f"{ast.unparse(stmt.target)} in {ast.unparse(stmt.iter)}"
        })
        all_blocks.append(for_block_id)
        
        # 将当前for循环推入栈，用于break/continue处理
        self.loop_stack.append({
            'type': 'for',
            'header_id': for_block_id,
            'stmt': stmt
        })
        
        # 2. 处理循环体
        body_blocks = self._process_statements_line_by_line(stmt.body, visited_functions, func_name)
        all_blocks.extend(body_blocks)
        
        # 3. 处理else子句（如果存在）
        else_blocks = []
        if stmt.orelse:
            else_blocks = self._process_statements_line_by_line(stmt.orelse, visited_functions, func_name)
            all_blocks.extend(else_blocks)
        
        # 弹出循环栈
        self.loop_stack.pop()
        
        # 建立连接
        self._connect_for_loop(for_block_id, body_blocks, else_blocks, stmt)
        
        return all_blocks
    
    def _process_while_loop(self, stmt: ast.While, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理while循环"""
        all_blocks = []
        
        # 1. while语句本身
        while_block_id = self._create_block(stmt, 'while_statement', func_name, {
            'condition': ast.unparse(stmt.test)
        })
        all_blocks.append(while_block_id)
        
        # 将当前while循环推入栈
        self.loop_stack.append({
            'type': 'while',
            'header_id': while_block_id,
            'stmt': stmt
        })
        
        # 2. 处理循环体
        body_blocks = self._process_statements_line_by_line(stmt.body, visited_functions, func_name)
        all_blocks.extend(body_blocks)
        
        # 3. 处理else子句（如果存在）
        else_blocks = []
        if stmt.orelse:
            else_blocks = self._process_statements_line_by_line(stmt.orelse, visited_functions, func_name)
            all_blocks.extend(else_blocks)
        
        # 弹出循环栈
        self.loop_stack.pop()
        
        # 建立连接
        self._connect_while_loop(while_block_id, body_blocks, else_blocks, stmt)
        
        return all_blocks
    
    def _process_if_statement(self, stmt: ast.If, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理if语句"""
        all_blocks = []
        
        # 1. if语句本身
        if_block_id = self._create_block(stmt, 'if_statement', func_name, {
            'condition': ast.unparse(stmt.test)
        })
        all_blocks.append(if_block_id)
        
        # 2. 处理then分支
        then_blocks = self._process_statements_line_by_line(stmt.body, visited_functions, func_name)
        all_blocks.extend(then_blocks)
        
        # 3. 处理else分支
        else_blocks = []
        if stmt.orelse:
            else_blocks = self._process_statements_line_by_line(stmt.orelse, visited_functions, func_name)
            all_blocks.extend(else_blocks)
        
        # 建立连接
        self._connect_if_statement(if_block_id, then_blocks, else_blocks, stmt)
        
        return all_blocks
    
    def _process_try_statement(self, stmt: ast.Try, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理try语句"""
        all_blocks = []
        
        # 将try推入栈
        try_info = {'stmt': stmt, 'blocks': []}
        self.try_stack.append(try_info)
        
        # 1. 处理try体
        try_blocks = self._process_statements_line_by_line(stmt.body, visited_functions, func_name)
        all_blocks.extend(try_blocks)
        try_info['try_blocks'] = try_blocks
        
        # 2. 处理except子句
        except_blocks_list = []
        for handler in stmt.handlers:
            # except语句本身
            except_code = "except"
            if handler.type:
                except_code += f" {ast.unparse(handler.type)}"
            if handler.name:
                except_code += f" as {handler.name}"
            except_code += ":"
            
            # 创建except块（手动创建，因为handler不是完整的语句）
            except_block_id = len(self.blocks)
            self.blocks.append({
                'id': except_block_id,
                'type': 'except_handler',
                'code': except_code,
                'ast_node': handler,
                'line_number': getattr(handler, 'lineno', 0),
                'function': func_name,
                'function_calls': []
            })
            all_blocks.append(except_block_id)
            
            # 处理except体
            except_body_blocks = self._process_statements_line_by_line(handler.body, visited_functions, func_name)
            all_blocks.extend(except_body_blocks)
            except_blocks_list.append([except_block_id] + except_body_blocks)
        
        try_info['except_blocks'] = except_blocks_list
        
        # 3. 处理else子句
        else_blocks = []
        if stmt.orelse:
            else_blocks = self._process_statements_line_by_line(stmt.orelse, visited_functions, func_name)
            all_blocks.extend(else_blocks)
        try_info['else_blocks'] = else_blocks
        
        # 4. 处理finally子句
        finally_blocks = []
        if stmt.finalbody:
            finally_blocks = self._process_statements_line_by_line(stmt.finalbody, visited_functions, func_name)
            all_blocks.extend(finally_blocks)
        try_info['finally_blocks'] = finally_blocks
        
        # 弹出try栈
        self.try_stack.pop()
        
        # 建立连接
        self._connect_try_statement(try_blocks, except_blocks_list, else_blocks, finally_blocks)
        
        return all_blocks
    
    def _process_with_statement(self, stmt: ast.With, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理with语句"""
        all_blocks = []
        
        # 1. with语句本身
        with_block_id = self._create_block(stmt, 'with_statement', func_name)
        all_blocks.append(with_block_id)
        
        # 2. 处理with体
        body_blocks = self._process_statements_line_by_line(stmt.body, visited_functions, func_name)
        all_blocks.extend(body_blocks)
        
        # 建立连接
        if body_blocks:
            self._add_connection(with_block_id, body_blocks[0], 'sequential')
            # with体执行完后可能需要清理连接，这里简化处理
        
        return all_blocks
    
    def _process_return(self, stmt: ast.Return, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理return语句"""
        # 检查是否包含列表推导式（直接或嵌套）
        if stmt.value and self._contains_list_comprehension(stmt.value):
            # 展开列表推导式为显式循环
            return self._expand_list_comprehension_return(stmt, visited_functions, func_name)
        # 检查是否包含生成器表达式
        elif stmt.value and self._contains_generator_expression(stmt.value):
            # 展开生成器表达式为显式循环
            return self._expand_generator_expression_return(stmt, visited_functions, func_name)
        else:
            # 普通return语句
            block_id = self._create_block(stmt, 'return', func_name)
            return [block_id]
    
    def _contains_list_comprehension(self, node: ast.AST) -> bool:
        """检查AST节点是否包含列表推导式（直接或嵌套）"""
        for child in ast.walk(node):
            if isinstance(child, ast.ListComp):
                return True
        return False
    
    def _contains_generator_expression(self, node: ast.AST) -> bool:
        """检查AST节点是否包含生成器表达式"""
        for child in ast.walk(node):
            if isinstance(child, ast.GeneratorExp):
                return True
        return False
    
    def _expand_generator_expression_return(self, stmt: ast.Return, visited_functions: Set[str], func_name: str) -> List[int]:
        """将包含生成器表达式的return语句展开为显式循环"""
        all_blocks = []
        
        # 找到生成器表达式
        generator_exp = None
        for child in ast.walk(stmt.value):
            if isinstance(child, ast.GeneratorExp):
                generator_exp = child
                break
        
        if not generator_exp:
            # 如果没有找到生成器表达式，回退到普通处理
            block_id = self._create_block(stmt, 'return', func_name)
            return [block_id]
        
        # 创建循环头（for x in iterable）
        for_clause = generator_exp.generators[0]  # 取第一个生成器
        
        # 创建for循环块
        for_code = f"for {ast.unparse(for_clause.target)} in {ast.unparse(for_clause.iter)}:"
        for_block_id = len(self.blocks)
        self.blocks.append({
            'id': for_block_id,
            'type': 'for_statement',
            'code': for_code,
            'ast_node': stmt,  # 关联到原始return语句
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': [],  # for循环头本身不调用函数
            'condition': f"{ast.unparse(for_clause.target)} in {ast.unparse(for_clause.iter)}"
        })
        all_blocks.append(for_block_id)
        
        # 创建条件检查块（if条件，如果有的话）
        condition_block_id = None
        if for_clause.ifs:
            condition_code = f"if {ast.unparse(for_clause.ifs[0])}:"
            condition_block_id = len(self.blocks)
            self.blocks.append({
                'id': condition_block_id,
                'type': 'if_statement',
                'code': condition_code,
                'ast_node': stmt,
                'line_number': getattr(stmt, 'lineno', 0),
                'function': func_name,
                'function_calls': [],
                'condition': ast.unparse(for_clause.ifs[0])
            })
            all_blocks.append(condition_block_id)
        
        # 创建函数调用块（生成器表达式的表达式部分）
        call_code = f"temp_result = {ast.unparse(generator_exp.elt)}"
        call_block_id = len(self.blocks)
        self.blocks.append({
            'id': call_block_id,
            'type': 'expression',
            'code': call_code,
            'ast_node': stmt,
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': self._extract_function_calls(generator_exp.elt)  # 这里有函数调用
        })
        all_blocks.append(call_block_id)
        
        # 创建收集块
        collect_code = "append(temp_result)"
        collect_block_id = len(self.blocks)
        self.blocks.append({
            'id': collect_block_id,
            'type': 'expression',
            'code': collect_code,
            'ast_node': stmt,
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': []
        })
        all_blocks.append(collect_block_id)
        
        # 创建return语句块 - 处理外层函数调用
        return_code = self._generate_return_code_with_outer_call(stmt, generator_exp)
        return_block_id = len(self.blocks)
        self.blocks.append({
            'id': return_block_id,
            'type': 'return',
            'code': return_code,
            'ast_node': stmt,
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': []
        })
        all_blocks.append(return_block_id)
        
        # 建立连接
        if condition_block_id is not None:
            # for -> 条件检查
            self._add_connection(for_block_id, condition_block_id, f'for_match:{for_code[4:-1]}')
            # 条件为真 -> 函数调用
            self._add_connection(condition_block_id, call_block_id, f'condition_true:{ast.unparse(for_clause.ifs[0])}')
            # 函数调用 -> 收集结果
            self._add_connection(call_block_id, collect_block_id, 'sequential')
            # 条件为假 -> 回到for循环头
            self._add_connection(condition_block_id, for_block_id, f'condition_false:{ast.unparse(for_clause.ifs[0])}')
        else:
            # for -> 函数调用
            self._add_connection(for_block_id, call_block_id, f'for_match:{for_code[4:-1]}')
            # 函数调用 -> 收集结果
            self._add_connection(call_block_id, collect_block_id, 'sequential')
        
        # 收集结果 -> 回到for循环头
        self._add_connection(collect_block_id, for_block_id, 'loop_back')
        
        # for循环结束 -> return
        self._add_connection(for_block_id, return_block_id, f'for_not_match:{for_code[4:-1]}')
        
        return all_blocks
    
    def _generate_return_code_with_outer_call_for_listcomp(self, stmt: ast.Return, listcomp: ast.ListComp) -> str:
        """生成列表推导式包含外层函数调用的return代码"""
        if stmt.value is None:
            return "return result"
        
        # 生成完整的表达式，但用result变量替换列表推导式
        return_expr = self._replace_listcomp_with_variable(stmt.value, listcomp, "result")
        return f"return {return_expr}"
    
    def _replace_listcomp_with_variable(self, node: ast.AST, target_listcomp: ast.ListComp, var_name: str) -> str:
        """在AST节点中用变量替换指定的列表推导式"""
        if node == target_listcomp:
            return var_name
        
        # 对于Call节点，递归处理参数
        if isinstance(node, ast.Call):
            # 处理函数名
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = ast.unparse(node.func)
            else:
                func_name = ast.unparse(node.func)
            
            # 处理参数
            args = []
            for arg in node.args:
                if arg == target_listcomp:
                    args.append(var_name)
                else:
                    args.append(self._replace_listcomp_with_variable(arg, target_listcomp, var_name))
            
            # 处理关键字参数
            kwargs = []
            for kw in node.keywords:
                if kw.value == target_listcomp:
                    kwargs.append(f"{kw.arg}={var_name}")
                else:
                    kwargs.append(f"{kw.arg}={self._replace_listcomp_with_variable(kw.value, target_listcomp, var_name)}")
            
            # 构建函数调用
            all_args = args + kwargs
            return f"{func_name}({', '.join(all_args)})"
        
        # 对于其他节点，递归处理子节点
        elif isinstance(node, ast.Attribute):
            value_str = self._replace_listcomp_with_variable(node.value, target_listcomp, var_name)
            return f"{value_str}.{node.attr}"
        
        elif isinstance(node, ast.Subscript):
            value_str = self._replace_listcomp_with_variable(node.value, target_listcomp, var_name)
            slice_str = self._replace_listcomp_with_variable(node.slice, target_listcomp, var_name)
            return f"{value_str}[{slice_str}]"
        
        elif isinstance(node, ast.BinOp):
            left_str = self._replace_listcomp_with_variable(node.left, target_listcomp, var_name)
            right_str = self._replace_listcomp_with_variable(node.right, target_listcomp, var_name)
            op_str = ast.unparse(node.op)
            return f"{left_str} {op_str} {right_str}"
        
        elif isinstance(node, ast.UnaryOp):
            operand_str = self._replace_listcomp_with_variable(node.operand, target_listcomp, var_name)
            op_str = ast.unparse(node.op)
            return f"{op_str}{operand_str}"
        
        # 对于其他情况，直接使用unparse
        else:
            return ast.unparse(node)
    
    def _generate_return_code_with_outer_call(self, stmt: ast.Return, generator_exp: ast.GeneratorExp) -> str:
        """生成包含外层函数调用的return代码"""
        if stmt.value is None:
            return "return temp_list"
        
        # 生成完整的表达式，但用temp_list变量替换生成器表达式
        return_expr = self._replace_generator_exp_with_variable(stmt.value, generator_exp, "temp_list")
        return f"return {return_expr}"
    
    def _replace_generator_exp_with_variable(self, node: ast.AST, target_generator: ast.GeneratorExp, var_name: str) -> str:
        """在AST节点中用变量替换指定的生成器表达式"""
        if node == target_generator:
            return var_name
        
        # 对于Call节点，递归处理参数
        if isinstance(node, ast.Call):
            # 处理函数名
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = ast.unparse(node.func)
            else:
                func_name = ast.unparse(node.func)
            
            # 处理参数
            args = []
            for arg in node.args:
                if arg == target_generator:
                    args.append(var_name)
                else:
                    args.append(self._replace_generator_exp_with_variable(arg, target_generator, var_name))
            
            # 处理关键字参数
            kwargs = []
            for kw in node.keywords:
                if kw.value == target_generator:
                    kwargs.append(f"{kw.arg}={var_name}")
                else:
                    kwargs.append(f"{kw.arg}={self._replace_generator_exp_with_variable(kw.value, target_generator, var_name)}")
            
            # 构建函数调用
            all_args = args + kwargs
            return f"{func_name}({', '.join(all_args)})"
        
        # 对于其他节点，递归处理子节点
        elif isinstance(node, ast.Attribute):
            value_str = self._replace_generator_exp_with_variable(node.value, target_generator, var_name)
            return f"{value_str}.{node.attr}"
        
        elif isinstance(node, ast.Subscript):
            value_str = self._replace_generator_exp_with_variable(node.value, target_generator, var_name)
            slice_str = self._replace_generator_exp_with_variable(node.slice, target_generator, var_name)
            return f"{value_str}[{slice_str}]"
        
        elif isinstance(node, ast.BinOp):
            left_str = self._replace_generator_exp_with_variable(node.left, target_generator, var_name)
            right_str = self._replace_generator_exp_with_variable(node.right, target_generator, var_name)
            op_str = ast.unparse(node.op)
            return f"{left_str} {op_str} {right_str}"
        
        elif isinstance(node, ast.UnaryOp):
            operand_str = self._replace_generator_exp_with_variable(node.operand, target_generator, var_name)
            op_str = ast.unparse(node.op)
            return f"{op_str}{operand_str}"
        
        # 对于其他情况，直接使用unparse
        else:
            return ast.unparse(node)
    
    def _expand_list_comprehension_return(self, stmt: ast.Return, visited_functions: Set[str], func_name: str) -> List[int]:
        """将包含列表推导式的return语句展开为显式循环"""
        all_blocks = []
        
        # 查找列表推导式
        comp = None
        for child in ast.walk(stmt.value):
            if isinstance(child, ast.ListComp):
                comp = child
                break
        
        if not comp:
            # 如果没有找到列表推导式，回退到普通处理
            block_id = self._create_block(stmt, 'return', func_name)
            return [block_id]
        
        # 创建循环头（for x in iterable）
        for_clause = comp.generators[0]  # 取第一个生成器
        
        # 创建for循环块
        for_code = f"for {ast.unparse(for_clause.target)} in {ast.unparse(for_clause.iter)}:"
        for_block_id = len(self.blocks)
        self.blocks.append({
            'id': for_block_id,
            'type': 'for_statement',
            'code': for_code,
            'ast_node': stmt,  # 关联到原始return语句
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': [],  # for循环头本身不调用函数
            'condition': f"{ast.unparse(for_clause.target)} in {ast.unparse(for_clause.iter)}"
        })
        all_blocks.append(for_block_id)
        
        # 创建条件检查块（if条件，如果有的话）
        condition_block_id = None
        if for_clause.ifs:
            condition_code = f"if {ast.unparse(for_clause.ifs[0])}:"
            condition_block_id = len(self.blocks)
            self.blocks.append({
                'id': condition_block_id,
                'type': 'if_statement',
                'code': condition_code,
                'ast_node': stmt,
                'line_number': getattr(stmt, 'lineno', 0),
                'function': func_name,
                'function_calls': [],
                'condition': ast.unparse(for_clause.ifs[0])
            })
            all_blocks.append(condition_block_id)
        
        # 创建函数调用块（列表推导式的表达式部分）
        call_code = f"append({ast.unparse(comp.elt)})"
        call_block_id = len(self.blocks)
        self.blocks.append({
            'id': call_block_id,
            'type': 'expression',
            'code': call_code,
            'ast_node': stmt,
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': self._extract_function_calls(comp.elt)  # 只有这里才有函数调用
        })
        all_blocks.append(call_block_id)
        
        # 创建return语句块 - 处理外层函数调用
        return_code = self._generate_return_code_with_outer_call_for_listcomp(stmt, comp)
        return_block_id = len(self.blocks)
        self.blocks.append({
            'id': return_block_id,
            'type': 'return',
            'code': return_code,
            'ast_node': stmt,
            'line_number': getattr(stmt, 'lineno', 0),
            'function': func_name,
            'function_calls': []
        })
        all_blocks.append(return_block_id)
        
        # 建立连接
        if condition_block_id is not None:
            # for -> 条件检查
            self._add_connection(for_block_id, condition_block_id, f'for_match:{for_code[4:-1]}')
            # 条件为真 -> 函数调用
            self._add_connection(condition_block_id, call_block_id, f'condition_true:{ast.unparse(for_clause.ifs[0])}')
            # 条件为假 -> 回到for循环头
            self._add_connection(condition_block_id, for_block_id, f'condition_false:{ast.unparse(for_clause.ifs[0])}')
        else:
            # for -> 函数调用
            self._add_connection(for_block_id, call_block_id, f'for_match:{for_code[4:-1]}')
        
        # 函数调用 -> 回到for循环头
        self._add_connection(call_block_id, for_block_id, 'loop_back')
        
        # for循环结束 -> return
        self._add_connection(for_block_id, return_block_id, f'for_not_match:{for_code[4:-1]}')
        
        return all_blocks
    
    def _process_break(self, stmt: ast.Break, func_name: str) -> List[int]:
        """处理break语句"""
        block_id = self._create_block(stmt, 'break', func_name)
        
        # 连接到最近的循环外部
        if self.loop_stack:
            current_loop = self.loop_stack[-1]
            # break跳出当前循环，这个连接将在循环处理完成后建立
            self.blocks[block_id]['break_target'] = current_loop
        
        return [block_id]
    
    def _process_continue(self, stmt: ast.Continue, func_name: str) -> List[int]:
        """处理continue语句"""
        block_id = self._create_block(stmt, 'continue', func_name)
        
        # 连接到最近的循环头部
        if self.loop_stack:
            current_loop = self.loop_stack[-1]
            self._add_connection(block_id, current_loop['header_id'], 'continue')
        
        return [block_id]
    
    def _process_pass(self, stmt: ast.Pass, func_name: str) -> List[int]:
        """处理pass语句"""
        block_id = self._create_block(stmt, 'pass', func_name)
        return [block_id]
    
    def _process_assert(self, stmt: ast.Assert, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理assert语句"""
        block_id = self._create_block(stmt, 'assert', func_name)
        return [block_id]
    
    def _process_raise(self, stmt: ast.Raise, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理raise语句"""
        block_id = self._create_block(stmt, 'raise', func_name)
        
        # raise会跳转到最近的except处理器
        if self.try_stack:
            # 这里可以建立到except的连接，但需要更复杂的逻辑
            pass
            
        return [block_id]
    
    def _process_delete(self, stmt: ast.Delete, func_name: str) -> List[int]:
        """处理del语句"""
        block_id = self._create_block(stmt, 'delete', func_name)
        return [block_id]
    
    def _process_expression(self, stmt: ast.Expr, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理表达式语句"""
        # 跳过字符串字面量（文档字符串）
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            return []  # 跳过文档字符串
        
        block_id = self._create_block(stmt, 'expression', func_name)
        return [block_id]
    
    def _process_import(self, stmt: ast.Import, func_name: str) -> List[int]:
        """处理import语句"""
        block_id = self._create_block(stmt, 'import', func_name)
        return [block_id]
    
    def _process_import_from(self, stmt: ast.ImportFrom, func_name: str) -> List[int]:
        """处理from...import语句"""
        block_id = self._create_block(stmt, 'import_from', func_name)
        return [block_id]
    
    def _process_global(self, stmt: ast.Global, func_name: str) -> List[int]:
        """处理global语句"""
        block_id = self._create_block(stmt, 'global', func_name)
        return [block_id]
    
    def _process_nonlocal(self, stmt: ast.Nonlocal, func_name: str) -> List[int]:
        """处理nonlocal语句"""
        block_id = self._create_block(stmt, 'nonlocal', func_name)
        return [block_id]
    
    def _process_unknown_statement(self, stmt: ast.stmt, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理未知类型的语句"""
        logger.warning(f"未知语句类型: {type(stmt).__name__}")
        block_id = self._create_block(stmt, 'unknown', func_name)
        return [block_id]
    
    def _extract_function_calls(self, node: ast.AST) -> List[str]:
        """提取AST节点中的函数调用"""
        function_calls = []
        
        # 对于控制结构（while、for、if），只提取条件部分的函数调用
        if isinstance(node, ast.While):
            # 只检查while条件，不检查循环体
            for child in ast.walk(node.test):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        func_name = child.func.id
                        if func_name in self.all_functions:
                            function_calls.append(func_name)
        elif isinstance(node, ast.For):
            # 只检查for迭代器，不检查循环体
            for child in ast.walk(node.iter):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        func_name = child.func.id
                        if func_name in self.all_functions:
                            function_calls.append(func_name)
        elif isinstance(node, ast.If):
            # 只检查if条件，不检查分支体
            for child in ast.walk(node.test):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        func_name = child.func.id
                        if func_name in self.all_functions:
                            function_calls.append(func_name)
        else:
            # 对于其他类型的节点，使用完整的遍历
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        func_name = child.func.id
                        if func_name in self.all_functions:
                            function_calls.append(func_name)
        
        return list(set(function_calls))  # 去重
    
    # 连接建立方法
    def _connect_sequential_blocks(self, block_ids: List[int]):
        """建立顺序块之间的连接"""
        for i in range(len(block_ids) - 1):
            current_block = self.blocks[block_ids[i]]
            next_block = self.blocks[block_ids[i + 1]]
            
            # 跳过控制结构块和不应该有顺序连接的块
            if current_block['type'] not in ['return', 'break', 'continue', 'raise', 
                                           'for_statement', 'while_statement', 'if_statement']:
                # 检查是否应该创建 sequential 连接
                if self._should_create_sequential_connection(current_block, next_block):
                    self._add_connection(block_ids[i], block_ids[i + 1], 'sequential')
    
    def _should_create_sequential_connection(self, current_block: Dict, next_block: Dict) -> bool:
        """判断是否应该创建sequential连接"""
        # 检查是否在同一函数内
        if current_block['function'] != next_block['function']:
            return False
        
        # 获取当前块和下一个块的AST节点
        current_node = current_block.get('ast_node')
        next_node = next_block.get('ast_node')
        
        if not current_node or not next_node:
            return False
        
        # 强化循环体检查：如果当前块在循环体内，绝对不创建到循环外的sequential连接
        if self._is_block_in_loop_body(current_block, next_block):
            return False
        
        # 特殊情况：finally块到return语句
        if self._is_finally_to_return(current_node, next_node, current_block['function']):
            return True
        
        # 检查是否在主函数的顶层（简单的顺序语句）
        if self._is_top_level_sequential(current_node, next_node, current_block['function']):
            return True
        
        # 检查是否在同一控制结构内的顺序语句
        if self._is_same_scope_sequential(current_node, next_node, current_block['function']):
            return True
        
        return False
    
    def _is_block_in_loop_body(self, current_block: Dict, next_block: Dict) -> bool:
        """检查当前块是否在循环体内而下一个块在循环外"""
        func_name = current_block['function']
        if func_name not in self.all_functions:
            return False
        
        func_node = self.all_functions[func_name]
        current_node = current_block.get('ast_node')
        next_node = next_block.get('ast_node')
        
        if not current_node or not next_node:
            return False
        
        # 遍历函数中的所有循环
        for stmt in ast.walk(func_node):
            if isinstance(stmt, (ast.For, ast.While)):
                # 检查当前块是否在循环体内
                current_in_loop = self._stmt_in_body(stmt.body, current_node)
                # 检查下一个块是否在循环体外
                next_in_loop = self._stmt_in_body(stmt.body, next_node)
                
                # 如果当前块在循环内，下一个块不在循环内，则不应该创建sequential连接
                if current_in_loop and not next_in_loop:
                    return True
        
        return False
    
    def _is_in_loop_body(self, node: ast.AST, func_name: str) -> bool:
        """检查节点是否在循环体内"""
        if func_name not in self.all_functions:
            return False
        
        func_node = self.all_functions[func_name]
        
        # 遍历函数中的所有循环
        for stmt in ast.walk(func_node):
            if isinstance(stmt, (ast.For, ast.While)):
                # 检查node是否在这个循环的body中
                if self._stmt_in_body(stmt.body, node):
                    return True
        
        return False
    
    def _is_in_same_loop_body(self, node1: ast.AST, node2: ast.AST, func_name: str) -> bool:
        """检查两个节点是否在同一个循环体内"""
        if func_name not in self.all_functions:
            return False
        
        func_node = self.all_functions[func_name]
        
        # 遍历函数中的所有循环
        for stmt in ast.walk(func_node):
            if isinstance(stmt, (ast.For, ast.While)):
                # 检查两个节点是否都在这个循环的body中
                if (self._stmt_in_body(stmt.body, node1) and 
                    self._stmt_in_body(stmt.body, node2)):
                    return True
        
        return False
    
    def _is_finally_to_return(self, current_node: ast.AST, next_node: ast.AST, func_name: str) -> bool:
        """检查是否是finally块到return语句的顺序"""
        if not isinstance(next_node, ast.Return):
            return False
        
        if func_name not in self.all_functions:
            return False
        
        func_node = self.all_functions[func_name]
        
        # 检查current_node是否在某个try语句的finally块中
        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Try) and stmt.finalbody:
                for finally_stmt in stmt.finalbody:
                    if finally_stmt == current_node:
                        # 检查next_node是否是try语句之后的return语句
                        if next_node in func_node.body:
                            try_idx = func_node.body.index(stmt)
                            return_idx = func_node.body.index(next_node)
                            return return_idx == try_idx + 1
        
        return False
    
    def _is_top_level_sequential(self, current_node: ast.AST, next_node: ast.AST, func_name: str) -> bool:
        """检查是否是函数顶层的顺序语句"""
        if func_name not in self.all_functions:
            return False
        
        func_node = self.all_functions[func_name]
        
        # 检查两个节点是否都在函数体的直接级别
        current_in_top = current_node in func_node.body
        next_in_top = next_node in func_node.body
        
        if current_in_top and next_in_top:
            # 检查是否是相邻的语句
            try:
                current_idx = func_node.body.index(current_node)
                next_idx = func_node.body.index(next_node)
                return next_idx == current_idx + 1
            except ValueError:
                return False
        
        return False
    
    def _is_same_scope_sequential(self, current_node: ast.AST, next_node: ast.AST, func_name: str) -> bool:
        """检查是否在同一作用域内的顺序语句"""
        if func_name not in self.all_functions:
            return False
        
        func_node = self.all_functions[func_name]
        
        # 新策略：检查执行顺序上的相邻关系
        def find_execution_order(target_node, parent_node, current_order=0):
            """找到节点在执行顺序中的位置"""
            if target_node == parent_node:
                return current_order
            
            order = current_order
            
            # 遍历当前节点的子节点，按执行顺序
            if hasattr(parent_node, 'body') and isinstance(parent_node.body, list):
                for stmt in parent_node.body:
                    if stmt == target_node:
                        return order
                    # 递归搜索
                    result = find_execution_order(target_node, stmt, order)
                    if result is not None:
                        return result
                    order += 1
            
            # 对于特殊结构（如if-else），需要特殊处理
            if isinstance(parent_node, ast.If):
                # if分支
                for stmt in parent_node.body:
                    if stmt == target_node:
                        return order
                    result = find_execution_order(target_node, stmt, order)
                    if result is not None:
                        return result
                    order += 1
                
                # else分支
                for stmt in parent_node.orelse:
                    if stmt == target_node:
                        return order
                    result = find_execution_order(target_node, stmt, order)
                    if result is not None:
                        return result
                    order += 1
            
            # 对于try-except-finally结构
            elif isinstance(parent_node, ast.Try):
                # try体
                for stmt in parent_node.body:
                    if stmt == target_node:
                        return order
                    result = find_execution_order(target_node, stmt, order)
                    if result is not None:
                        return result
                    order += 1
                
                # except处理器
                for handler in parent_node.handlers:
                    if hasattr(handler, 'body'):
                        for stmt in handler.body:
                            if stmt == target_node:
                                return order
                            result = find_execution_order(target_node, stmt, order)
                            if result is not None:
                                return result
                            order += 1
                
                # finally体
                for stmt in parent_node.finalbody:
                    if stmt == target_node:
                        return order
                    result = find_execution_order(target_node, stmt, order)
                    if result is not None:
                        return result
                    order += 1
            
            # 递归处理其他类型的子节点
            for child in ast.iter_child_nodes(parent_node):
                if child == target_node:
                    return order
                result = find_execution_order(target_node, child, order)
                if result is not None:
                    return result
                order += 1
            
            return None
        
        current_order = find_execution_order(current_node, func_node)
        next_order = find_execution_order(next_node, func_node)
        
        # 检查是否在执行顺序上相邻
        if (current_order is not None and next_order is not None and 
            next_order == current_order + 1):
            return True
        
        return False
    
    def _is_crossing_control_structure_boundary(self, current_node: ast.AST, next_node: ast.AST) -> bool:
        """检查是否跨越了控制结构边界"""
        # 找到包含这两个节点的函数
        func_name = None
        for name, func_node in self.all_functions.items():
            if self._node_in_function(current_node, func_node) and self._node_in_function(next_node, func_node):
                func_name = name
                break
        
        if not func_name:
            return True  # 如果不在同一函数内，肯定跨越了边界
        
        func_node = self.all_functions[func_name]
        
        # 检查是否在不同的控制结构分支中
        current_path = self._get_node_path_in_function(current_node, func_node)
        next_path = self._get_node_path_in_function(next_node, func_node)
        
        if not current_path or not next_path:
            return True
        
        # 检查路径是否在同一分支中
        return not self._paths_in_same_branch(current_path, next_path)
    
    def _node_in_function(self, node: ast.AST, func_node: ast.FunctionDef) -> bool:
        """检查节点是否在函数内"""
        for child in ast.walk(func_node):
            if child == node:
                return True
        return False
    
    def _get_node_path_in_function(self, target_node: ast.AST, func_node: ast.FunctionDef) -> List[str]:
        """获取节点在函数中的路径"""
        def find_path(node, path):
            if node == target_node:
                return path
            
            if isinstance(node, ast.If):
                # 检查 if 体
                for stmt in node.body:
                    result = find_path(stmt, path + ['if_body'])
                    if result:
                        return result
                # 检查 else 体
                for stmt in node.orelse:
                    result = find_path(stmt, path + ['else_body'])
                    if result:
                        return result
            elif isinstance(node, ast.For):
                # 检查 for 体
                for stmt in node.body:
                    result = find_path(stmt, path + ['for_body'])
                    if result:
                        return result
            elif isinstance(node, ast.While):
                # 检查 while 体
                for stmt in node.body:
                    result = find_path(stmt, path + ['while_body'])
                    if result:
                        return result
            elif hasattr(node, 'body') and isinstance(node.body, list):
                for stmt in node.body:
                    result = find_path(stmt, path)
                    if result:
                        return result
            
            return None
        
        return find_path(func_node, [])
    
    def _paths_in_same_branch(self, path1: List[str], path2: List[str]) -> bool:
        """检查两个路径是否在同一分支中"""
        # 如果路径长度不同，检查较短的路径是否是较长路径的前缀
        min_len = min(len(path1), len(path2))
        
        for i in range(min_len):
            if path1[i] != path2[i]:
                # 如果在 if/else 分支中分叉，则不在同一分支
                if ('if_body' in [path1[i], path2[i]] and 'else_body' in [path1[i], path2[i]]):
                    return False
                return False
        
        return True
    
    def _connect_for_loop(self, for_block_id: int, body_blocks: List[int], 
                         else_blocks: List[int], stmt: ast.For):
        """建立for循环的连接"""
        condition = f"{ast.unparse(stmt.target)} in {ast.unparse(stmt.iter)}"
        
        # for -> 循环体（有元素时）
        if body_blocks:
            self._add_connection(for_block_id, body_blocks[0], f'for_match:{condition}')
        
        # for -> else分支（无元素时）
        if else_blocks:
            self._add_connection(for_block_id, else_blocks[0], f'for_not_match:{condition}')
        
        # 注意：for循环的not match case和loop_back会在_add_control_structure_exit_connections中处理
    
    def _connect_while_loop(self, while_block_id: int, body_blocks: List[int], 
                           else_blocks: List[int], stmt: ast.While):
        """建立while循环的连接"""
        condition = ast.unparse(stmt.test)
        
        # while -> 循环体（条件为真时）
        if body_blocks:
            self._add_connection(while_block_id, body_blocks[0], f'condition_true:{condition}')
            
            # 循环体所有最后执行的块 -> while（循环回去）
            last_body_blocks = self._find_all_last_executable_blocks(body_blocks, stmt.body)
            for last_block in last_body_blocks:
                self._add_connection(last_block, while_block_id, 'loop_back')
        
        # while -> else分支（条件为假时）
        if else_blocks:
            self._add_connection(while_block_id, else_blocks[0], f'condition_false:{condition}')
        else:
            # 没有else分支时，添加默认的condition_false连接
            # 这个连接会在_add_control_structure_exit_connections中处理具体的目标
            pass
        
        # 注意：while循环结束后到下一个语句的连接会在更高层处理
    
    def _connect_if_statement(self, if_block_id: int, then_blocks: List[int], 
                             else_blocks: List[int], stmt: ast.If):
        """建立if语句的连接"""
        condition = ast.unparse(stmt.test)
        
        # if -> then分支（条件为真时）
        if then_blocks:
            self._add_connection(if_block_id, then_blocks[0], f'condition_true:{condition}')
        
        # if -> else分支（条件为假时）
        if else_blocks:
            self._add_connection(if_block_id, else_blocks[0], f'condition_false:{condition}')
        else:
            # 如果没有明确的else子句，但代码中有隐含的else逻辑
            # 检查是否有其他语句可以作为else的目标
            implicit_else_target = self._find_implicit_else_target(if_block_id, stmt)
            if implicit_else_target is not None:
                self._add_connection(if_block_id, implicit_else_target, f'condition_false:{condition}')
            # 注意：如果找不到隐含的else目标，这里不添加连接
            # 连接将在_add_if_statement_exit_connections中添加，那时所有块都已创建完成
        
        # 注意：分支出口连接将在_add_control_structure_exit_connections中处理
    
    def _add_if_branch_exit_connections(self, if_stmt: ast.If, then_blocks: List[int], else_blocks: List[int]):
        """为if语句分支的最后执行块添加到下一个语句的连接"""
        # 获取函数名
        func_name = None
        if then_blocks:
            func_name = self.blocks[then_blocks[0]]['function']
        elif else_blocks:
            func_name = self.blocks[else_blocks[0]]['function']
        
        if func_name is None or func_name not in self.all_functions:
            return
        
        # 找到if语句后的下一个语句块
        next_stmt_block = self._find_next_statement_in_function_body(
            self.all_functions[func_name], if_stmt)
        
        if next_stmt_block is None:
            return
        
        # 为then分支的最后执行块添加连接
        if then_blocks:
            last_then_blocks = self._find_last_executable_blocks_in_branch(then_blocks, if_stmt.body)
            for last_block in last_then_blocks:
                self._add_connection(last_block, next_stmt_block, 'sequential')
        
        # 为else分支的最后执行块添加连接
        if else_blocks:
            last_else_blocks = self._find_last_executable_blocks_in_branch(else_blocks, if_stmt.orelse)
            for last_block in last_else_blocks:
                self._add_connection(last_block, next_stmt_block, 'sequential')
    
    def _find_last_executable_blocks_in_branch(self, branch_blocks: List[int], branch_stmts: List[ast.stmt]) -> List[int]:
        """找到分支中最后执行的块"""
        if not branch_blocks:
            return []
        
        last_blocks = []
        
        # 找到分支中最后一个语句对应的块
        if branch_stmts:
            last_stmt = branch_stmts[-1]
            for block_id in branch_blocks:
                block = self.blocks[block_id]
                if block.get('ast_node') == last_stmt:
                    # 只包含非控制流终止的块
                    if block['type'] not in ['return', 'break', 'continue', 'raise']:
                        last_blocks.append(block_id)
        
        # 如果没有找到，返回最后一个非控制流块
        if not last_blocks:
            for block_id in reversed(branch_blocks):
                block = self.blocks[block_id]
                if block['type'] not in ['return', 'break', 'continue', 'raise', 'if_statement', 'for_statement', 'while_statement']:
                    last_blocks.append(block_id)
                    break
        
        return last_blocks
    
    def _find_implicit_else_target(self, if_block_id: int, if_stmt: ast.If) -> Optional[int]:
        """找到if语句的隐含else目标（当没有显式else时）"""
        if_block = self.blocks[if_block_id]
        func_name = if_block['function']
        
        if func_name not in self.all_functions:
            return None
        
        func_node = self.all_functions[func_name]
        
        # 检查是否在循环体中
        parent_loop = self._find_parent_loop(func_node, if_stmt)
        if parent_loop:
            # 在循环体中，检查是否有下一个语句
            next_stmt_in_loop = self._find_next_statement_in_loop_body(func_node, if_stmt)
            if next_stmt_in_loop is not None:
                return next_stmt_in_loop
            else:
                # 没有下一个语句，loop back到循环头
                return self._find_block_for_ast_node(parent_loop)
        
        # 不在循环中，找到函数体中的下一个语句
        next_stmt_block = self._find_next_statement_in_function_body(func_node, if_stmt)
        return next_stmt_block
    
    def _connect_try_statement(self, try_blocks: List[int], except_blocks_list: List[List[int]], 
                              else_blocks: List[int], finally_blocks: List[int]):
        """建立try语句的连接"""
        # try块到except块的连接（异常发生时）
        for try_block_id in try_blocks:
            for except_blocks in except_blocks_list:
                if except_blocks:
                    self._add_connection(try_block_id, except_blocks[0], 'exception')
        
        # try块到else块的连接（无异常时）
        if try_blocks and else_blocks:
            last_try_block = self._find_last_executable_block(try_blocks)
            if last_try_block is not None:
                self._add_connection(last_try_block, else_blocks[0], 'no_exception')
        
        # 限制finally连接：只有特定的最后执行块需要连接到finally
        if finally_blocks:
            # 1. try块的最后执行块（正常完成时）
            if try_blocks:
                last_try_block = self._find_try_block_last_executable(try_blocks)
                if last_try_block is not None:
                    self._add_connection(last_try_block, finally_blocks[0], 'finally')
            
            # 2. 每个except块的最后执行块
            for except_blocks in except_blocks_list:
                if except_blocks:
                    last_except_block = self._find_last_executable_block(except_blocks)
                    if last_except_block is not None:
                        self._add_connection(last_except_block, finally_blocks[0], 'finally')
            
            # 3. else块的最后执行块（如果存在）
            if else_blocks:
                last_else_block = self._find_last_executable_block(else_blocks)
                if last_else_block is not None:
                    self._add_connection(last_else_block, finally_blocks[0], 'finally')
    
    def _find_try_block_last_executable(self, try_blocks: List[int]) -> Optional[int]:
        """找到try块中最后一个可执行的块（排除循环内的块）"""
        # 在try块中，我们需要找到最后一个真正会执行到的块
        # 排除循环内的块，因为它们有自己的控制流
        for block_id in reversed(try_blocks):
            block = self.blocks[block_id]
            # 如果是while循环，它是try块的最后一个结构
            if block['type'] == 'while_statement':
                return block_id
        
        # 如果没有找到while循环，返回最后一个非控制流块
        return self._find_last_executable_block(try_blocks)
    
    def _add_control_structure_exit_connections(self, statements: List[ast.stmt], block_ids: List[int]):
        """添加控制结构到下一个语句的连接"""
        # 为每个控制结构块添加正确的退出连接
        for block in self.blocks:
            if block['type'] == 'for_statement':
                self._add_for_loop_exit_connections(block)
            elif block['type'] == 'while_statement':
                self._add_while_loop_exit_connections(block)
            elif block['type'] == 'if_statement':
                self._add_if_statement_exit_connections(block)
        
        # 处理break语句的跳出连接  
        self._add_break_exit_connections(statements, {})
        
        # 处理函数调用连接
        self._add_function_call_connections()
        
        # 最后处理loop_back连接，避免与exit连接重复
        self._add_loop_back_connections()
    
    def _add_for_loop_exit_connections(self, for_block: Dict):
        """为for循环添加退出连接"""
        for_block_id = for_block['id']
        for_node = for_block.get('ast_node')
        
        if not for_node:
            return
        
        # 检查是否是真正的For节点
        if not isinstance(for_node, ast.For):
            # 如果不是For节点，使用块的condition信息
            condition = for_block.get('condition', '')
            if condition:
                # 检查是否已经有for_not_match连接
                has_not_match_connection = any(
                    conn['from'] == for_block_id and conn['type'].startswith('for_not_match:')
                    for conn in self.connections
                )
                
                if not has_not_match_connection:
                    # 找到for循环的下一个目标
                    next_target = self._find_generic_loop_exit_target(for_block)
                    if next_target is not None:
                        self._add_connection(for_block_id, next_target, f'for_not_match:{condition}')
            return
        
        condition = f"{ast.unparse(for_node.target)} in {ast.unparse(for_node.iter)}"
        
        # 检查是否已经有for_not_match连接（如果有else分支）
        has_not_match_connection = any(
            conn['from'] == for_block_id and conn['type'].startswith('for_not_match:')
            for conn in self.connections
        )
        
        if not has_not_match_connection:
            # 没有else分支，需要添加not match连接
            # 找到for循环的下一个目标
            next_target = self._find_for_loop_exit_target(for_node, for_block['function'])
            if next_target is not None:
                self._add_connection(for_block_id, next_target, f'for_not_match:{condition}')
    
    def _add_while_loop_exit_connections(self, while_block: Dict):
        """为while循环添加退出连接"""
        while_block_id = while_block['id']
        while_node = while_block.get('ast_node')
        
        if not while_node:
            return
        
        # 检查是否是真正的While节点
        if not isinstance(while_node, ast.While):
            # 如果不是While节点，使用块的condition信息
            condition = while_block.get('condition', '')
            if condition:
                # 检查是否已经有condition_false连接
                has_false_connection = any(
                    conn['from'] == while_block_id and conn['type'].startswith('condition_false:')
                    for conn in self.connections
                )
                
                if not has_false_connection:
                    # 找到while循环的下一个目标
                    next_target = self._find_generic_loop_exit_target(while_block)
                    if next_target is not None:
                        self._add_connection(while_block_id, next_target, f'condition_false:{condition}')
            return
        
        condition = while_block.get('condition', ast.unparse(while_node.test))
        
        # 检查是否已经有condition_false连接（如果有else分支）
        has_false_connection = any(
            conn['from'] == while_block_id and conn['type'].startswith('condition_false:')
            for conn in self.connections
        )
        
        if not has_false_connection:
            # 没有else分支，需要添加condition_false连接
            # 找到while循环的下一个目标
            next_target = self._find_while_loop_exit_target(while_node, while_block['function'])
            if next_target is not None:
                self._add_connection(while_block_id, next_target, f'condition_false:{condition}')
    
    def _find_generic_loop_exit_target(self, loop_block: Dict) -> Optional[int]:
        """找到通用循环的退出目标"""
        func_name = loop_block['function']
        loop_line = loop_block['line_number']
        
        # 找到同一函数内循环行之后的下一个语句
        for block in self.blocks:
            if (block['function'] == func_name and 
                block['line_number'] >= loop_line and
                block['id'] != loop_block['id'] and
                block['type'] == 'return'):
                return block['id']
        
        return None
    
    def _add_if_statement_exit_connections(self, if_block: Dict):
        """为if语句添加退出连接"""
        if_block_id = if_block['id']
        if_node = if_block.get('ast_node')
        
        if not if_node:
            return
        
        # 检查是否是真正的If节点
        if not isinstance(if_node, ast.If):
            # 如果不是If节点，使用块的condition信息
            condition = if_block.get('condition', '')
            if condition:
                # 检查是否已经有condition_false连接
                has_false_connection = any(
                    conn['from'] == if_block_id and conn['type'].startswith('condition_false:')
                    for conn in self.connections
                )
                
                if not has_false_connection:
                    # 找到if语句的下一个目标
                    next_target = self._find_generic_if_exit_target(if_block)
                    if next_target is not None:
                        self._add_connection(if_block_id, next_target, f'condition_false:{condition}')
            return
        
        condition = if_block.get('condition', ast.unparse(if_node.test))
        
        # 检查if语句是否有else分支
        has_else_branch = bool(if_node.orelse)
        
        # 检查是否已经有condition_false连接（如果有else分支）
        has_false_connection = any(
            conn['from'] == if_block_id and conn['type'].startswith('condition_false:')
            for conn in self.connections
        )
        
        # 只有当没有else分支且没有condition_false连接时才添加连接
        if not has_else_branch and not has_false_connection:
            # 没有else分支，需要添加condition_false连接
            # 对于在循环体中的if语句，需要特殊处理以找到正确的同级下一个语句
            func_node = self.all_functions[if_block['function']]
            parent_loop = self._find_parent_loop(func_node, if_node)
            
            if parent_loop:
                # 在循环体中，直接在循环体中找到if语句的下一个语句
                next_target = self._find_next_statement_in_loop_body_by_line(func_node, if_node)
                if next_target is None:
                    # 如果找不到下一个语句，则回到循环头
                    next_target = self._find_block_for_ast_node(parent_loop)
            else:
                # 不在循环中，使用原有逻辑
                next_target = self._find_if_statement_exit_target(if_node, if_block['function'])
            
            if next_target is not None:
                self._add_connection(if_block_id, next_target, f'condition_false:{condition}')
        elif not has_else_branch and has_false_connection:
            # 如果已经有连接，但是在循环体中，需要检查连接是否正确
            func_node = self.all_functions[if_block['function']]
            parent_loop = self._find_parent_loop(func_node, if_node)
            
            if parent_loop:
                # 在循环体中，检查是否有正确的连接到同级下一个语句
                correct_target = self._find_next_statement_in_loop_body_by_line(func_node, if_node)
                if correct_target is not None:
                    # 检查现有连接是否正确
                    existing_false_conn = None
                    for conn in self.connections:
                        if (conn['from'] == if_block_id and 
                            conn['type'].startswith('condition_false:')):
                            existing_false_conn = conn
                            break
                    
                    if existing_false_conn and existing_false_conn['to'] != correct_target:
                        # 现有连接不正确，需要更新
                        self.connections.remove(existing_false_conn)
                        self._add_connection(if_block_id, correct_target, f'condition_false:{condition}')
        
        # 添加if分支的出口连接
        # 找到then和else分支的块
        then_blocks = []
        else_blocks = []
        
        # 遍历所有blocks，找到属于这个if语句分支的blocks
        for block in self.blocks:
            if block['function'] == if_block['function']:
                block_node = block.get('ast_node')
                if block_node:
                    # 检查是否在then分支中
                    if self._stmt_in_body(if_node.body, block_node):
                        then_blocks.append(block['id'])
                    # 检查是否在else分支中
                    elif if_node.orelse and self._stmt_in_body(if_node.orelse, block_node):
                        else_blocks.append(block['id'])
        
        # 调用分支出口连接逻辑
        self._add_if_branch_exit_connections(if_node, then_blocks, else_blocks)
    
    def _find_generic_if_exit_target(self, if_block: Dict) -> Optional[int]:
        """找到通用if语句的退出目标"""
        func_name = if_block['function']
        if_line = if_block['line_number']
        
        # 找到同一函数内if语句对应的for循环头
        for block in self.blocks:
            if (block['function'] == func_name and 
                block['line_number'] == if_line and
                block['id'] != if_block['id'] and
                block['type'] == 'for_statement'):
                return block['id']
        
        return None
    
    def _find_for_loop_exit_target(self, for_node: ast.For, func_name: str) -> Optional[int]:
        """找到for循环的退出目标"""
        if func_name not in self.all_functions:
            return None
        
        func_node = self.all_functions[func_name]
        
        # 无论是否在嵌套循环中，for循环都应该退出到它在其直接容器中的下一个语句
        next_stmt_block = self._find_next_statement_in_function_body(func_node, for_node)
        return next_stmt_block
    
    def _find_while_loop_exit_target(self, while_node: ast.While, func_name: str) -> Optional[int]:
        """找到while循环的退出目标"""
        if func_name not in self.all_functions:
            return None
        
        func_node = self.all_functions[func_name]
        
        # 检查是否在嵌套循环中
        parent_loop = self._find_parent_loop(func_node, while_node)
        if parent_loop:
            # 在嵌套循环中，退出到父循环
            return self._find_block_for_ast_node(parent_loop)
        
        # 不在嵌套循环中，找到函数体中的下一个语句
        next_stmt_block = self._find_next_statement_in_function_body(func_node, while_node)
        return next_stmt_block
    
    def _find_if_statement_exit_target(self, if_node: ast.If, func_name: str) -> Optional[int]:
        """找到if语句的退出目标"""
        if func_name not in self.all_functions:
            return None
        
        func_node = self.all_functions[func_name]
        
        # 检查是否在循环体中
        parent_loop = self._find_parent_loop(func_node, if_node)
        if parent_loop:
            # 在循环体中，检查是否有下一个语句
            next_stmt_in_loop = self._find_next_statement_in_loop_body(func_node, if_node)
            if next_stmt_in_loop is not None:
                return next_stmt_in_loop
            else:
                # 没有下一个语句，loop back到循环头
                return self._find_block_for_ast_node(parent_loop)
        
        # 不在循环中，找到函数体中的下一个语句
        next_stmt_block = self._find_next_statement_in_function_body(func_node, if_node)
        return next_stmt_block
    
    def _find_parent_loop(self, func_node: ast.FunctionDef, target_node: ast.AST) -> Optional[ast.AST]:
        """找到包含目标节点的父循环"""
        def find_in_body(body, target, current_loop=None):
            for stmt in body:
                if stmt == target:
                    return current_loop
                
                if isinstance(stmt, (ast.For, ast.While)):
                    # 检查target是否在这个循环内
                    if self._stmt_in_body(stmt.body, target):
                        # 继续递归查找更深层的循环
                        deeper_loop = find_in_body(stmt.body, target, stmt)
                        return deeper_loop if deeper_loop else stmt
                    # 递归检查循环内的嵌套结构
                    result = find_in_body(stmt.body, target, stmt)
                    if result:
                        return result
                elif isinstance(stmt, ast.If):
                    result = find_in_body(stmt.body, target, current_loop)
                    if result:
                        return result
                    if stmt.orelse:
                        result = find_in_body(stmt.orelse, target, current_loop)
                        if result:
                            return result
                elif isinstance(stmt, ast.Try):
                    result = find_in_body(stmt.body, target, current_loop)
                    if result:
                        return result
                    for handler in stmt.handlers:
                        result = find_in_body(handler.body, target, current_loop)
                        if result:
                            return result
                    if stmt.orelse:
                        result = find_in_body(stmt.orelse, target, current_loop)
                        if result:
                            return result
                    if stmt.finalbody:
                        result = find_in_body(stmt.finalbody, target, current_loop)
                        if result:
                            return result
            return None
        
        return find_in_body(func_node.body, target_node)
    
    def _find_block_for_ast_node(self, ast_node: ast.AST) -> Optional[int]:
        """找到AST节点对应的块ID"""
        for block in self.blocks:
            if block.get('ast_node') == ast_node:
                return block['id']
        return None
    
    def _find_all_last_executable_blocks(self, body_blocks: List[int], ast_body: List[ast.stmt]) -> List[int]:
        """找到循环体中所有可能的最后执行块"""
        last_blocks = []
        
        # 遍历所有块，找到循环体中的最后执行块
        for block_id in body_blocks:
            block = self.blocks[block_id]
            
            # 如果是return语句，它不会loop back
            if block['type'] == 'return':
                continue
            
            # 如果是break语句，它不会loop back
            if block['type'] == 'break':
                continue
            
            # 如果是continue语句，它会直接跳到循环头
            if block['type'] == 'continue':
                continue
            
            # 如果是if语句，它不会直接loop back（会通过其他连接处理）
            if block['type'] == 'if_statement':
                continue
            
            # 检查这个块是否是某个语句的最后执行部分
            if self._is_last_executable_block_in_loop(block_id, body_blocks, ast_body):
                last_blocks.append(block_id)
        
        return last_blocks
    
    def _is_last_executable_block_in_loop(self, block_id: int, body_blocks: List[int], ast_body: List[ast.stmt]) -> bool:
        """检查块是否是循环体中的最后执行块"""
        block = self.blocks[block_id]
        block_ast = block.get('ast_node')
        
        if not block_ast:
            return False
        
        # 检查是否是循环体中最后一个语句的一部分
        if ast_body:
            last_stmt = ast_body[-1]
            
            # 如果是最后一个语句本身
            if block_ast == last_stmt:
                return True
            
            # 如果是最后一个语句的子语句（如if语句的then/else分支）
            if self._is_part_of_statement(block_ast, last_stmt):
                # 进一步检查是否是该语句的最后执行路径
                return self._is_last_path_in_statement(block_ast, last_stmt)
        
        return False
    
    def _is_part_of_statement(self, block_ast: ast.AST, parent_stmt: ast.stmt) -> bool:
        """检查块是否是某个语句的一部分"""
        for node in ast.walk(parent_stmt):
            if node == block_ast:
                return True
        return False
    
    def _is_last_path_in_statement(self, block_ast: ast.AST, parent_stmt: ast.stmt) -> bool:
        """检查块是否是语句的最后执行路径"""
        if isinstance(parent_stmt, ast.If):
            # 对于if语句，both then和else分支的最后语句都可能是最后执行的
            if parent_stmt.body and block_ast == parent_stmt.body[-1]:
                return True
            if parent_stmt.orelse and block_ast == parent_stmt.orelse[-1]:
                return True
        elif isinstance(parent_stmt, (ast.For, ast.While)):
            # 对于循环语句，循环体的最后语句是最后执行的
            if parent_stmt.body and block_ast == parent_stmt.body[-1]:
                return True
        else:
            # 对于其他语句，如果块就是语句本身，则是最后执行的
            return block_ast == parent_stmt
        
        return False
    
    def _find_next_statement_in_loop_body(self, func_node: ast.FunctionDef, if_node: ast.AST) -> Optional[int]:
        """在循环体中找到if语句后的下一个语句"""
        def find_if_in_loop_body(loop_body, target_if):
            for i, stmt in enumerate(loop_body):
                if stmt == target_if:
                    # 找到if语句，返回下一个语句
                    if i + 1 < len(loop_body):
                        next_stmt = loop_body[i + 1]
                        # 找到对应的块
                        for block in self.blocks:
                            if block.get('ast_node') == next_stmt:
                                return block['id']
                    return None
                
                # 递归搜索嵌套的if结构
                if isinstance(stmt, ast.If):
                    # 检查if分支
                    result = find_if_in_loop_body(stmt.body, target_if)
                    if result is not None:
                        return result
                    # 检查else分支
                    if stmt.orelse:
                        result = find_if_in_loop_body(stmt.orelse, target_if)
                        if result is not None:
                            return result
            return None
        
        # 遍历函数中的所有循环
        for stmt in ast.walk(func_node):
            if isinstance(stmt, (ast.For, ast.While)):
                result = find_if_in_loop_body(stmt.body, if_node)
                if result is not None:
                    return result
        
        return None
    
    def _find_next_statement_in_function_body(self, func_node: ast.FunctionDef, target_stmt: ast.AST) -> Optional[int]:
        """在函数体中找到目标语句后的下一个语句对应的块"""
        func_name = func_node.name  # 获取函数名
        
        def find_stmt_context_with_parent(body, target, parent_stmt=None):
            """递归查找目标语句，返回容器、索引和父语句"""
            for i, stmt in enumerate(body):
                if stmt == target:
                    # 找到目标语句，返回容器、索引和父语句
                    return body, i, parent_stmt
                
                # 递归查找嵌套结构，传递当前语句作为父语句
                if isinstance(stmt, ast.For):
                    result = find_stmt_context_with_parent(stmt.body, target, stmt)
                    if result is not None:
                        return result
                elif isinstance(stmt, ast.While):
                    result = find_stmt_context_with_parent(stmt.body, target, stmt)
                    if result is not None:
                        return result
                elif isinstance(stmt, ast.If):
                    result = find_stmt_context_with_parent(stmt.body, target, stmt)
                    if result is not None:
                        return result
                    if stmt.orelse:
                        result = find_stmt_context_with_parent(stmt.orelse, target, stmt)
                        if result is not None:
                            return result
                elif isinstance(stmt, ast.Try):
                    result = find_stmt_context_with_parent(stmt.body, target, stmt)
                    if result is not None:
                        return result
                    # 检查except处理块
                    for handler in stmt.handlers:
                        result = find_stmt_context_with_parent(handler.body, target, stmt)
                        if result is not None:
                            return result
                    # 检查else和finally块
                    if stmt.orelse:
                        result = find_stmt_context_with_parent(stmt.orelse, target, stmt)
                        if result is not None:
                            return result
                    if stmt.finalbody:
                        result = find_stmt_context_with_parent(stmt.finalbody, target, stmt)
                        if result is not None:
                            return result
            return None
        
        # 找到目标语句所在的上下文
        context = find_stmt_context_with_parent(func_node.body, target_stmt)
        if context is None:
            return None
        
        container_body, stmt_index, parent_stmt = context
        
        # 在直接容器中找下一个语句
        if stmt_index + 1 < len(container_body):
            next_stmt = container_body[stmt_index + 1]
            # 找到对应的块，优先使用AST节点对象匹配以避免代码内容重复的问题
            
            # 方法1：AST节点对象匹配（最可靠）
            for block in self.blocks:
                if block.get('ast_node') == next_stmt:
                    return block['id']
            
            # 方法2：行号匹配（需要确保在同一函数内）
            if hasattr(next_stmt, 'lineno'):
                for block in self.blocks:
                    if (block.get('line_number') == next_stmt.lineno and 
                        block.get('function') == func_name):
                        return block['id']
            
            # 方法3：代码内容匹配（最后手段，需要同时匹配函数名和行号）
            try:
                next_stmt_code = ast.unparse(next_stmt).strip()
                if hasattr(next_stmt, 'lineno'):
                    for block in self.blocks:
                        if (block.get('code', '').strip() == next_stmt_code and
                            block.get('function') == func_name and
                            block.get('line_number') == next_stmt.lineno):
                            return block['id']
            except:
                pass
        
        # 如果直接容器中没有下一个语句，且有父语句，则递归查找父语句的下一个语句
        if parent_stmt is not None:
            return self._find_next_statement_in_function_body(func_node, parent_stmt)
        
        return None
    
    def _find_next_statement_in_loop_body_by_line(self, func_node: ast.FunctionDef, if_node: ast.AST) -> Optional[int]:
        """在循环体中找到if语句后的下一个语句 - 使用行号匹配"""
        if not hasattr(if_node, 'lineno'):
            return None
        
        if_line = if_node.lineno
        
        # 遍历函数中的所有循环
        for stmt in ast.walk(func_node):
            if isinstance(stmt, (ast.For, ast.While)):
                # 检查if语句是否在这个循环内
                if self._stmt_in_body(stmt.body, if_node):
                    # 在循环体中找到if语句的下一个语句
                    for i, loop_stmt in enumerate(stmt.body):
                        if hasattr(loop_stmt, 'lineno') and loop_stmt.lineno == if_line:
                            # 找到if语句，查找下一个语句
                            if i + 1 < len(stmt.body):
                                next_stmt = stmt.body[i + 1]
                                next_line = getattr(next_stmt, 'lineno', None)
                                if next_line:
                                    # 根据行号找到对应的块
                                    for block in self.blocks:
                                        if block.get('line_number') == next_line:
                                            return block['id']
                                    
                                    # 如果行号匹配失败，尝试代码内容匹配
                                    next_code = ast.unparse(next_stmt).strip()
                                    for block in self.blocks:
                                        if block.get('code', '').strip() == next_code:
                                            return block['id']
                            break
        
        return None
    
    def _stmt_in_body(self, body: List[ast.stmt], target_stmt: ast.AST) -> bool:
        """检查语句是否在指定body中"""
        for stmt in body:
            if stmt == target_stmt:
                return True
            
            # 递归搜索嵌套结构
            if isinstance(stmt, ast.If):
                if self._stmt_in_body(stmt.body, target_stmt):
                    return True
                if stmt.orelse:
                    if self._stmt_in_body(stmt.orelse, target_stmt):
                        return True
            elif isinstance(stmt, (ast.For, ast.While)):
                if self._stmt_in_body(stmt.body, target_stmt):
                    return True
            elif isinstance(stmt, ast.Try):
                if self._stmt_in_body(stmt.body, target_stmt):
                    return True
                for handler in stmt.handlers:
                    if self._stmt_in_body(handler.body, target_stmt):
                        return True
                if stmt.orelse:
                    if self._stmt_in_body(stmt.orelse, target_stmt):
                        return True
                if stmt.finalbody:
                    if self._stmt_in_body(stmt.finalbody, target_stmt):
                        return True
        
        return False
    
    def _find_containing_loop(self, func_node: ast.FunctionDef, break_stmt: ast.AST) -> Optional[ast.AST]:
        """找到包含break语句的最内层循环"""
        def find_innermost_loop(body, target):
            innermost_loop = None
            
            for stmt in body:
                if stmt == target:
                    return innermost_loop  # 找到目标，返回当前最内层循环
                
                if isinstance(stmt, (ast.For, ast.While)):
                    # 检查break是否在这个循环内
                    if self._stmt_in_body(stmt.body, target):
                        # 递归查找更内层的循环
                        deeper_loop = find_innermost_loop(stmt.body, target)
                        # 如果有更内层的循环，返回更内层的；否则返回当前循环
                        return deeper_loop if deeper_loop else stmt
                    # 即使break不在这个循环内，也要递归检查嵌套结构
                    result = find_innermost_loop(stmt.body, target)
                    if result:
                        return result
                elif isinstance(stmt, ast.If):
                    result = find_innermost_loop(stmt.body, target)
                    if result:
                        return result
                    if stmt.orelse:
                        result = find_innermost_loop(stmt.orelse, target)
                        if result:
                            return result
                elif isinstance(stmt, ast.Try):
                    # 搜索try块
                    result = find_innermost_loop(stmt.body, target)
                    if result:
                        return result
                    # 搜索except块
                    for handler in stmt.handlers:
                        result = find_innermost_loop(handler.body, target)
                        if result:
                            return result
                    # 搜索else块
                    if stmt.orelse:
                        result = find_innermost_loop(stmt.orelse, target)
                        if result:
                            return result
                    # 搜索finally块
                    if stmt.finalbody:
                        result = find_innermost_loop(stmt.finalbody, target)
                        if result:
                            return result
            return innermost_loop
        
        return find_innermost_loop(func_node.body, break_stmt)

    def _add_function_call_connections(self):
        """添加函数调用连接"""
        for i, block in enumerate(self.blocks):
            # 检查所有有函数调用的块类型，包括assign
            if block.get('function_calls'):
                for func_call in block['function_calls']:
                    if func_call in self.all_functions:
                        # 找到被调用函数的第一个块
                        func_first_block = self._find_function_first_block(func_call)
                        if func_first_block is not None:
                            self._add_connection(block['id'], func_first_block, 'function_call')
                        
                        # 找到被调用函数的返回块，连接回调用点的下一个逻辑位置
                        func_return_blocks = self._find_function_return_blocks(func_call)
                        for return_block in func_return_blocks:
                            # 对于复杂表达式（如列表推导式），函数返回后应该继续表达式的执行
                            # 但是这里我们简化处理，直接连接到调用块本身，表示函数调用完成
                            # 实际上列表推导式会多次调用函数，每次调用完成后继续下一次迭代
                            next_target = self._find_function_call_continuation(block, func_call)
                            if next_target is not None:
                                self._add_connection(return_block, next_target, 'function_return')
    
    def _find_function_call_continuation(self, call_block: Dict, func_call: str) -> Optional[int]:
        """找到函数调用完成后的继续执行点"""
        # 检查调用块是否是展开的列表推导式中的表达式块
        if call_block['type'] == 'expression' and 'append(' in call_block['code']:
            # 这是展开的列表推导式中的函数调用块
            # 返回后应该回到这个块本身，然后由loop_back连接处理
            return call_block['id']
        
        # 对于其他类型的函数调用，返回到调用块本身
        return call_block['id']
    
    def _is_comprehension_call(self, call_block: Dict) -> bool:
        """检查是否是列表推导式中的函数调用"""
        code = call_block['code']
        # 简单检查是否包含列表推导式的特征
        return '[' in code and 'for' in code and 'in' in code
    
    def _remove_sequential_connection_from_block(self, block_id: int):
        """移除指定块的sequential连接"""
        self.connections = [conn for conn in self.connections 
                           if not (conn['from'] == block_id and conn['type'] == 'sequential')]
    
    def _find_function_first_block(self, func_name: str) -> Optional[int]:
        """找到函数的第一个块"""
        if func_name not in self.all_functions:
            return None
        
        # 查找该函数的第一个块（按块ID顺序）
        for block in self.blocks:
            if block['function'] == func_name:
                return block['id']
        return None
    
    def _find_function_return_blocks(self, func_name: str) -> List[int]:
        """找到函数的所有返回块"""
        return_blocks = []
        for block in self.blocks:
            if (block['function'] == func_name and 
                block['type'] == 'return'):
                return_blocks.append(block['id'])
        return return_blocks
    
    def _find_next_block_after_function_call(self, call_block_index: int) -> Optional[int]:
        """找到函数调用后的下一个块"""
        # 函数调用后的下一个块应该是同一函数内的下一个语句
        call_block = self.blocks[call_block_index]
        call_function = call_block['function']
        
        # 找到同一函数内的下一个块
        for i in range(call_block_index + 1, len(self.blocks)):
            block = self.blocks[i]
            if (block['function'] == call_function and 
                block['type'] in ['statement', 'expression'] and
                block['line_number'] > call_block['line_number']):
                return block['id']
        
        return None
    
    def _add_break_exit_connections(self, statements: List[ast.stmt], stmt_to_first_block: Dict[int, int]):
        """为break语句添加跳出循环的连接"""
        # 找到所有break块和循环外的下一个语句
        for block in self.blocks:
            if block['type'] == 'break':
                # 找到break所在的循环，然后找到循环后的下一个语句
                loop_exit_block = self._find_loop_exit_block(block['id'], statements, stmt_to_first_block)
                if loop_exit_block is not None:
                    self._add_connection(block['id'], loop_exit_block, 'break_exit')
    
    def _find_loop_exit_block(self, break_block_id: int, statements: List[ast.stmt], stmt_to_first_block: Dict[int, int]) -> Optional[int]:
        """找到break语句跳出的目标块"""
        break_block = self.blocks[break_block_id]
        break_stmt = break_block.get('ast_node')
        
        if not break_stmt:
            return None
        
        # 找到包含这个break的函数
        func_name = break_block['function']
        if func_name not in self.all_functions:
            return None
        
        func_node = self.all_functions[func_name]
        
        # 找到包含break的循环语句
        loop_stmt = self._find_containing_loop(func_node, break_stmt)
        if not loop_stmt:
            return None
        
        # 特殊处理：在try-except结构中，for循环后的下一个语句是while循环
        # 这里我们需要在try块内找到for循环后的下一个语句
        if isinstance(loop_stmt, ast.For):
            # 在try块内找到for循环后的下一个语句
            try_next_stmt = self._find_next_statement_in_try_block(func_node, loop_stmt)
            if try_next_stmt is not None:
                return try_next_stmt
        
        # 找到循环语句后的下一个语句
        return self._find_next_statement_in_function_body(func_node, loop_stmt)
    
    def _find_next_statement_in_try_block(self, func_node: ast.FunctionDef, for_stmt: ast.For) -> Optional[int]:
        """在try块内找到for循环后的下一个语句"""
        # 遍历函数中的所有try语句
        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Try):
                # 在try块的body中找到for循环
                for i, try_stmt in enumerate(stmt.body):
                    if try_stmt == for_stmt:
                        # 找到for循环，查看下一个语句
                        if i + 1 < len(stmt.body):
                            next_stmt = stmt.body[i + 1]
                            # 找到对应的块
                            for block in self.blocks:
                                if block.get('ast_node') == next_stmt:
                                    return block['id']
        return None
    
    def _find_next_block_after_for_loop(self, for_stmt: ast.For, stmt_index: int, 
                                        statements: List[ast.stmt], stmt_to_first_block: Dict[int, int]) -> Optional[int]:
        """找到for循环后的下一个块"""
        # 使用通用方法找到for语句后的下一个语句
        for for_block in self.blocks:
            if for_block.get('ast_node') == for_stmt:
                func_name = for_block['function']
                if func_name in self.all_functions:
                    func_node = self.all_functions[func_name]
                    return self._find_next_statement_in_function_body(func_node, for_stmt)
        return None
    
    def _find_next_block_after_while_loop(self, while_stmt: ast.While, stmt_index: int,
                                         statements: List[ast.stmt], stmt_to_first_block: Dict[int, int]) -> Optional[int]:
        """找到while循环后的下一个块"""
        # 使用通用方法找到while语句后的下一个语句
        for while_block in self.blocks:
            if while_block.get('ast_node') == while_stmt:
                func_name = while_block['function']
                if func_name in self.all_functions:
                    func_node = self.all_functions[func_name]
                    return self._find_next_statement_in_function_body(func_node, while_stmt)
        return None

    def _find_next_block_after_loop(self, loop_stmt: ast.stmt) -> Optional[int]:
        """找到循环后的下一个块"""
        loop_end_line = getattr(loop_stmt, 'end_lineno', getattr(loop_stmt, 'lineno', 0) + 10)
        
        # 找到循环结束后的第一个块
        for block in self.blocks:
            if block['line_number'] > loop_end_line and block['type'] not in ['break', 'continue']:
                return block['id']
        return None
    
    def _is_break_in_loop(self, break_block_id: int, loop_stmt: ast.stmt) -> bool:
        """检查break块是否在指定循环内"""
        # 简化实现：通过块ID范围判断
        break_line = self.blocks[break_block_id]['line_number']
        loop_start = getattr(loop_stmt, 'lineno', 0)
        loop_end = getattr(loop_stmt, 'end_lineno', loop_start + 100)
        return loop_start < break_line <= loop_end

    def _count_blocks_for_statement(self, stmt: ast.stmt) -> int:
        """计算单个语句会产生多少个块"""
        if isinstance(stmt, (ast.For, ast.While, ast.If)):
            # 控制结构会产生多个块，这里简化计算
            count = 1  # 控制结构本身的块
            if isinstance(stmt, (ast.For, ast.While)):
                count += len(stmt.body)
                if stmt.orelse:
                    count += len(stmt.orelse)
            elif isinstance(stmt, ast.If):
                count += len(stmt.body)
                if stmt.orelse:
                    count += len(stmt.orelse)
            return count
        elif isinstance(stmt, ast.Try):
            count = len(stmt.body)
            for handler in stmt.handlers:
                count += 1 + len(handler.body)  # except块 + except体
            if stmt.orelse:
                count += len(stmt.orelse)
            if stmt.finalbody:
                count += len(stmt.finalbody)
            return count
        else:
            return 1  # 普通语句只产生一个块
    
    def _generate_cfg_text(self) -> str:
        """生成CFG的文本表示"""
        header = f"G describes a control flow graph of Function `{self.funcname}`\nIn this graph:"
        
        # 找到主函数的第一个执行块作为起点
        entry_block_id = self._find_main_function_entry_block()
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
            elif conn_type == 'function_call':
                edge_descriptions.append(f"Block {conn['from']} function call points to Block {conn['to']}.")
            elif conn_type == 'function_return':
                edge_descriptions.append(f"Block {conn['from']} function return points to Block {conn['to']}.")
            elif conn_type == 'function_body':
                edge_descriptions.append(f"Block {conn['from']} function body points to Block {conn['to']}.")
            elif conn_type.startswith('for_match:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('for_not_match:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} not match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('condition_true:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('condition_false:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} not match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type == 'exception':
                edge_descriptions.append(f"Block {conn['from']} exception points to Block {conn['to']}.")
            elif conn_type == 'no_exception':
                edge_descriptions.append(f"Block {conn['from']} no exception points to Block {conn['to']}.")
            elif conn_type == 'finally':
                edge_descriptions.append(f"Block {conn['from']} finally points to Block {conn['to']}.")
            else:
                edge_descriptions.append(f"Block {conn['from']} {conn_type} points to Block {conn['to']}.")
        
        # 只为入口函数（主函数）的return语句添加到END的连接
        for block in self.blocks:
            if (block['type'] == 'return' and 
                block['function'] == self.main_function):
                edge_descriptions.append(f"Block {block['id']} unconditional points to Block {end_block_id}.")
        
        # 组合所有部分
        body_parts = entry_info + block_descriptions + edge_descriptions
        body = "\n".join(body_parts)
        return f"{header}\n{body}"
    
    def _find_main_function_entry_block(self) -> Optional[int]:
        """找到主函数的第一个执行块（入口点）"""
        # 找到主函数的第一个非函数定义的块
        for block in self.blocks:
            if (block['function'] == self.main_function and 
                block['type'] != 'function_def'):
                return block['id']
        return None
    
    def print_features(self):
        """打印CFG特征信息"""
        logger.info("=================Complete Function CFG=================")
        logger.info(f"主函数: {self.main_function}")
        logger.info(f"函数签名: {self.funcname}")
        logger.info(f"所有函数: {list(self.all_functions.keys())}")
        logger.info(f"块数量: {self.block_num}")
        logger.info(f"连接数量: {len(self.connections)}")
        
        logger.info("块信息:")
        for block in self.blocks:
            logger.info(f"  Block {block['id']} ({block['type']}): {block['code'][:50]}...")
        
        logger.info("连接信息:")
        for conn in self.connections:
            logger.info(f"  {conn['from']} --{conn['type']}--> {conn['to']}")
        
        logger.info(f"CFG文本表示:\n{self.cfg_text}")
        logger.info("=================Complete Function CFG=================")

    def _find_last_executable_block(self, block_ids: List[int]) -> Optional[int]:
        """找到最后一个可执行的块（不是break/continue/return）"""
        for block_id in reversed(block_ids):
            if self.blocks[block_id]['type'] not in ['break', 'continue', 'return', 'raise']:
                return block_id
        return None
    
    def _find_all_last_executable_blocks(self, body_blocks: List[int], ast_body: List[ast.stmt]) -> List[int]:
        """找到循环体中所有可能的最后执行块"""
        last_blocks = []
        
        # 遍历所有块，找到循环体中的最后执行块
        for block_id in body_blocks:
            block = self.blocks[block_id]
            
            # 如果是return语句，它不会loop back
            if block['type'] == 'return':
                continue
            
            # 如果是break语句，它不会loop back
            if block['type'] == 'break':
                continue
            
            # 如果是continue语句，它会直接跳到循环头
            if block['type'] == 'continue':
                continue
            
            # 如果是if语句，它不会直接loop back（会通过其他连接处理）
            if block['type'] == 'if_statement':
                continue
            
            # 检查这个块是否是某个语句的最后执行部分
            if self._is_last_executable_block_in_loop(block_id, body_blocks, ast_body):
                last_blocks.append(block_id)
        
        return last_blocks
    
    def _find_blocks_for_ast_node(self, ast_node: ast.stmt, candidate_blocks: List[int]) -> List[int]:
        """找到AST节点对应的所有块"""
        matching_blocks = []
        for block_id in candidate_blocks:
            if self.blocks[block_id].get('ast_node') == ast_node:
                matching_blocks.append(block_id)
            # 对于if语句，还需要包含其body中的块
            elif isinstance(ast_node, ast.If):
                # 递归检查if语句内的所有语句
                if self._block_belongs_to_if_statement(block_id, ast_node):
                    matching_blocks.append(block_id)
        return matching_blocks
    
    def _block_belongs_to_if_statement(self, block_id: int, if_node: ast.If) -> bool:
        """检查块是否属于if语句的某个分支"""
        block_ast = self.blocks[block_id].get('ast_node')
        if not block_ast:
            return False
        
        # 检查是否在if分支中
        for stmt in if_node.body:
            if block_ast == stmt:
                return True
            # 递归检查嵌套结构
            if self._ast_contains_node(stmt, block_ast):
                return True
        
        # 检查是否在else分支中
        for stmt in if_node.orelse:
            if block_ast == stmt:
                return True
            if self._ast_contains_node(stmt, block_ast):
                return True
        
        return False
    
    def _ast_contains_node(self, container: ast.AST, target: ast.AST) -> bool:
        """检查AST容器是否包含目标节点"""
        for node in ast.walk(container):
            if node == target:
                return True
        return False
    
    def _find_last_blocks_in_if_branch(self, branch_stmts: List[ast.stmt], if_blocks: List[int]) -> List[int]:
        """找到if分支中的最后执行块"""
        if not branch_stmts:
            return []
        
        last_branch_stmt = branch_stmts[-1]
        
        # 找到该分支最后语句对应的块
        for block_id in if_blocks:
            if self.blocks[block_id].get('ast_node') == last_branch_stmt:
                # 确保是可执行块
                if self.blocks[block_id]['type'] not in ['break', 'continue', 'return', 'raise']:
                    return [block_id]
        
        return []
    


    def _process_function_calls_in_blocks(self, visited_functions: Set[str]):
        """处理所有块中的函数调用"""
        # 收集所有需要处理的函数调用，避免重复处理
        functions_to_process = set()
        for block in self.blocks:
            if block.get('function_calls'):
                for func_call in block['function_calls']:
                    if func_call in self.all_functions and func_call not in visited_functions:
                        functions_to_process.add(func_call)
        
        # 处理每个函数调用
        for func_call in functions_to_process:
            logger.info(f"发现函数调用: {func_call}")
            # 递归处理被调用的函数
            self._build_function_cfg(func_call, visited_functions.copy())

    def _add_loop_back_connections(self):
        """添加loop_back连接，避免与exit连接重复"""
        for block in self.blocks:
            if block['type'] in ['for_statement', 'while_statement']:
                loop_block_id = block['id']
                loop_node = block.get('ast_node')
                
                if not loop_node:
                    continue
                
                # 找到循环体的所有块
                body_blocks = self._find_loop_body_blocks(loop_node, block['function'])
                
                # 找到循环体中的最后执行块
                last_body_blocks = self._find_all_last_executable_blocks(body_blocks, getattr(loop_node, 'body', []))
                
                # 为每个最后执行块添加loop_back连接（如果没有其他跳转）
                for last_block in last_body_blocks:
                    # 检查这个块是否已经有其他跳转连接
                    has_other_jump = any(
                        conn['from'] == last_block and 
                        (conn['type'] in ['return', 'break', 'continue'] or
                         conn['type'].startswith('for_not_match:') or
                         conn['type'].startswith('condition_false:') or
                         conn['type'].startswith('condition_true:'))
                        for conn in self.connections
                    )
                    
                    if not has_other_jump:
                        self._add_connection(last_block, loop_block_id, 'loop_back')
    
    def _find_loop_body_blocks(self, loop_node: ast.AST, func_name: str) -> List[int]:
        """找到循环体中的所有块"""
        body_blocks = []
        
        for block in self.blocks:
            if block['function'] == func_name:
                block_ast = block.get('ast_node')
                if block_ast and self._is_in_loop_body(loop_node, block_ast):
                    body_blocks.append(block['id'])
        
        return body_blocks
    
    def _is_in_loop_body(self, loop_node: ast.AST, target_node: ast.AST) -> bool:
        """检查目标节点是否在循环体内"""
        if not hasattr(loop_node, 'body'):
            return False
        
        return self._stmt_in_body(loop_node.body, target_node)

    def _process_function_def(self, stmt: ast.FunctionDef, visited_functions: Set[str], func_name: str) -> List[int]:
        """处理函数定义语句"""
        all_blocks = []
        
        # 函数定义本身不作为Block，只处理函数体
        if stmt.name not in visited_functions:
            # 将内部函数添加到访问列表，避免重复处理
            visited_functions.add(stmt.name)
            
            # 递归处理内部函数的CFG
            inner_func_blocks = self._process_statements_line_by_line(stmt.body, visited_functions, stmt.name)
            all_blocks.extend(inner_func_blocks)
        
        return all_blocks


# 测试函数
# def helper_function(x):
#     if x > 0:
#         return x * 2
#     else:
#         return x * -1

# def main_function(arr):
#     result = []
    
#     try:
#         for i in range(len(arr)):
#             if arr[i] > 0:
#                 continue
#             elif arr[i] == 0:
#                 break

#             processed = helper_function(arr[i])
#             result.append(processed)
            
#         while len(result) > 5:
#             result.pop()
    
#     except Exception as e:
#         print("fffff")
#         result = []
#     finally:
#         print("eeeee")
#     return result
def test_complete_cfg():
    """测试完整的CFG构建器"""
    test_code = '''
def helper_function(x):
    if x > 0:
        return x * 2
    else:
        return x * -1

def main_function(arr):
    result = []
    
    try:
        for i in range(len(arr)):
            if arr[i] > 0:
                continue
            elif arr[i] == 0:
                break

            processed = helper_function(arr[i])
            result.append(processed)
            
        while len(result) > 5:
            result.pop()
    
    except Exception as e:
        print("fffff")
        result = []
    finally:
        print("eeeee")
    return result
'''
    
    # 写入测试文件
    test_file = "test_complete_cfg.py"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)
    
    try:
        # 测试完整CFG构建器
        cfg = TextCFG(test_file, "main_function")
        cfg.print_features()
        
        print(f"\n生成的块数量: {cfg.block_num}")
        print(f"生成的连接数量: {len(cfg.connections)}")
        
    finally:
        # 清理测试文件
        import os
        if os.path.exists(test_file):
            os.remove(test_file)


if __name__ == "__main__":
    test_complete_cfg() 