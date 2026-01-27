import re
import operator

class LogicEngine:
    def __init__(self):
        self.operators = {
            '+': operator.add,
            '-': operator.sub,
            '*': operator.mul,
            '/': operator.truediv,
            '%': operator.mod,
            '>': operator.gt,
            '<': operator.lt,
            '>=': operator.ge,
            '<=': operator.le,
            '==': operator.eq,
            '!=': operator.ne,
        }

    def evaluate_formula(self, formula, context):
        """
        Evaluates a formula like "{mark1} + {mark2}" using the context dictionary.
        """
        try:
            # Replace placeholders {field_name} with values from context
            expression = formula
            for key, value in context.items():
                pattern = re.compile(re.escape('{' + key + '}'), re.IGNORECASE)
                # If value is numeric, keep it; if it's text, we might need quotes (but formulas are usually numeric)
                val_str = str(value) if value is not None else '0'
                expression = pattern.sub(val_str, expression)

            # Safety check: only allow numbers, operators, and parentheses
            if not re.match(r'^[0-9\.\s\+\-\*\/\%\(\)]*$', expression):
                return "Error: Invalid characters in expression"

            # Evaluate the expression
            # Note: eval() is used here with caution after the whitelist check above.
            return eval(expression, {"__builtins__": None}, {})
        except Exception as e:
            return f"Error: {str(e)}"

    def evaluate_boolean(self, logic, context):
        """
        Evaluates boolean logic.
        logic: a list of conditions or a complex expression.
        For now, let's support a simple list of conditions with 'AND'/'OR'.
        Simplified logic schema:
        {
            "operator": "AND",
            "conditions": [
                {"field": "total", "op": ">", "value": 250},
                {"field": "attendance", "op": ">=", "value": 90}
            ]
        }
        """
        if not logic:
            return False

        try:
            op = logic.get('operator', 'AND')
            conditions = logic.get('conditions', [])
            
            results = []
            for cond in conditions:
                field_val = context.get(cond['field'])
                target_val = cond['value']
                condition_op = cond['op']

                # Convert both to float if possible for numeric comparison
                try:
                    f_val = float(field_val)
                    t_val = float(target_val)
                except (ValueError, TypeError):
                    f_val = field_val
                    t_val = target_val

                if condition_op == '>':
                    results.append(f_val > t_val)
                elif condition_op == '<':
                    results.append(f_val < t_val)
                elif condition_op == '==':
                    results.append(f_val == t_val)
                elif condition_op == '>=':
                    results.append(f_val >= t_val)
                elif condition_op == '<=':
                    results.append(f_val <= t_val)
                elif condition_op == '!=':
                    results.append(f_val != t_val)
                elif condition_op == 'contains':
                    results.append(str(t_val).lower() in str(f_val).lower())
                elif condition_op == 'starts_with':
                    results.append(str(f_val).lower().startswith(str(t_val).lower()))
                elif condition_op == 'ends_with':
                    results.append(str(f_val).lower().endswith(str(t_val).lower()))

            if op == 'AND':
                return all(results) if results else True
            elif op == 'OR':
                return any(results) if results else False
            
            return False
        except Exception as e:
            print(f"Logic Error: {e}")
            return False

def get_logic_engine():
    return LogicEngine()
