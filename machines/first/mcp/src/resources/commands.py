"""
Available Commands Resource

Resource that exposes available machine commands and their parameters.
"""

import json
import inspect
import typing
from puda_drivers.machines import First


def _get_type_name(annotation) -> str:
    """Extract a clean type name from a type annotation."""
    if annotation == inspect.Parameter.empty:
        return "Any"
    
    # Handle typing constructs (Optional, Union, List, etc.)
    if hasattr(typing, 'get_origin') and typing.get_origin(annotation):
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        
        # Handle Optional[T] -> "Optional[T]" or just the inner type if it's Optional[None, T]
        if origin is typing.Union:
            # Filter out NoneType for Optional
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                return _get_type_name(non_none_args[0])
            return f"Union[{', '.join(_get_type_name(arg) for arg in args)}]"
        
        # Handle List[T], Dict[K, V], etc.
        if args:
            args_str = ', '.join(_get_type_name(arg) for arg in args)
            origin_name = origin.__name__ if hasattr(origin, '__name__') else str(origin)
            return f"{origin_name}[{args_str}]"
        return origin.__name__ if hasattr(origin, '__name__') else str(origin)
    
    # Handle built-in types and classes
    if hasattr(annotation, '__name__'):
        return annotation.__name__
    
    # Fallback to string representation, but clean it up
    type_str = str(annotation)
    if type_str.startswith("<class '") and type_str.endswith("'>"):
        return type_str[9:-2]  # Extract "str" from "<class 'str'>"
    
    return type_str


async def get_available_commands_data() -> str:
    """Returns a JSON string describing all available First machine commands and their parameters.
    
    Provides comprehensive documentation of all commands available for the First machine,
    including parameter types, descriptions, and example usage.
    
    Returns:
        str: JSON-formatted object containing command documentation.
    """
    commands = []
    
    # Get all public instance methods from the First class (excluding private methods starting with _)
    for name, method in inspect.getmembers(First, predicate=inspect.isfunction):
        if not name.startswith('_'):
            # Get method signature
            sig = inspect.signature(method)
            
            # Extract parameters (skip 'self')
            params = {}
            
            for param_name, param in sig.parameters.items():
                if param_name == 'self':
                    continue
                    
                param_type_str = _get_type_name(param.annotation)
                param_default = param.default if param.default != inspect.Parameter.empty else None
                param_required = param.default == inspect.Parameter.empty
                
                param_info = {
                    "name": param_name,
                    "type": param_type_str,
                    "default": str(param_default) if param_default is not None else None,
                    "required": param_required
                }
                params[param_name] = param_info
            
            # Get docstring
            docstring = inspect.getdoc(method) or ""
            
            # Extract description from docstring (first line or first paragraph)
            description = docstring.split('\n\n')[0].strip() if docstring else ""
            
            command_info = {
                "command": name,
                "description": description,
                "parameters": params,
                "full_docstring": docstring
            }
            commands.append(command_info)
    
    return json.dumps(commands, indent=2)

