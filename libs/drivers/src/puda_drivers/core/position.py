"""
Position class for handling multi-axis positions.

Supports flexible axis definitions with default x, y, z, a axes.
Provides JSON conversion, arithmetic operations, and dictionary/tuple compatibility.
"""

import json
import copy
from typing import Dict, Optional, Tuple, Union, Any


class Position:
    """
    Represents a position in multi-axis space.
    
    Default axes are x, y, z, a, but can support any number of axes.
    Supports addition, subtraction, JSON conversion, and dictionary/tuple access.
    """
    
    def __init__(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        a: Optional[float] = None,
        **kwargs: float
    ):
        """
        Initialize a Position with axis values.
        
        Args:
            x: X axis value (optional)
            y: Y axis value (optional)
            z: Z axis value (optional)
            a: A axis value (optional)
            **kwargs: Additional axis values (e.g., b=10.0, c=20.0)
        
        Examples:
            >>> pos = Position(x=10, y=20, z=30, a=0)
            >>> pos = Position(x=10, y=20, b=5.0, c=10.0)
        """
        self._axes: Dict[str, float] = {}
        
        # Set default axes if provided
        if x is not None:
            self._axes["x"] = float(x)
        if y is not None:
            self._axes["y"] = float(y)
        if z is not None:
            self._axes["z"] = float(z)
        if a is not None:
            self._axes["a"] = float(a)
        
        # Set additional axes
        for axis_name, value in kwargs.items():
            self._axes[axis_name.lower()] = float(value)
    
    @classmethod
    def from_dict(cls, data: Dict[str, float], case_sensitive: bool = False) -> "Position":
        """
        Create a Position from a dictionary.
        
        Args:
            data: Dictionary with axis names as keys and values as floats
            case_sensitive: If False, converts keys to lowercase. Defaults to False.
        
        Returns:
            Position instance
        
        Examples:
            >>> pos = Position.from_dict({"X": 10, "Y": 20, "Z": 30})
            >>> pos = Position.from_dict({"x": 10, "y": 20, "z": 30})
        """
        if case_sensitive:
            return cls(**{k: v for k, v in data.items()})
        else:
            return cls(**{k.lower(): v for k, v in data.items()})
    
    @classmethod
    def from_json(cls, json_str: str) -> "Position":
        """
        Create a Position from a JSON string.
        
        Args:
            json_str: JSON string containing axis values
        
        Returns:
            Position instance
        
        Examples:
            >>> pos = Position.from_json('{"x": 10, "y": 20, "z": 30}')
        """
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def from_tuple(cls, values: Tuple[float, ...], axes: Optional[Tuple[str, ...]] = None) -> "Position":
        """
        Create a Position from a tuple of values.
        
        Args:
            values: Tuple of float values
            axes: Optional tuple of axis names. Defaults to ("x", "y", "z", "a")
        
        Returns:
            Position instance
        
        Examples:
            >>> pos = Position.from_tuple((10, 20, 30))
            >>> pos = Position.from_tuple((10, 20, 30, 0), ("x", "y", "z", "a"))
        """
        if axes is None:
            default_axes = ("x", "y", "z", "a")
            axes = default_axes[:len(values)]
        
        if len(values) != len(axes):
            raise ValueError(f"Number of values ({len(values)}) must match number of axes ({len(axes)})")
        
        return cls(**{axis: val for axis, val in zip(axes, values)})
    
    def to_dict(self, uppercase: bool = False) -> Dict[str, float]:
        """
        Convert Position to a dictionary.
        
        Args:
            uppercase: If True, returns uppercase keys (X, Y, Z, A). Defaults to False.
        
        Returns:
            Dictionary with axis names as keys
        
        Examples:
            >>> pos = Position(x=10, y=20)
            >>> pos.to_dict()  # {"x": 10, "y": 20}
            >>> pos.to_dict(uppercase=True)  # {"X": 10, "Y": 20}
        """
        if uppercase:
            return {k.upper(): v for k, v in self._axes.items()}
        return self._axes.copy()
    
    def to_json(self) -> str:
        """
        Convert Position to a JSON string.
        
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict())
    
    def to_tuple(self, axes: Optional[Tuple[str, ...]] = None) -> Tuple[float, ...]:
        """
        Convert Position to a tuple of values.
        
        Args:
            axes: Optional tuple of axis names to include. Defaults to all axes in order.
        
        Returns:
            Tuple of float values
        
        Examples:
            >>> pos = Position(x=10, y=20, z=30)
            >>> pos.to_tuple()  # (10.0, 20.0, 30.0)
            >>> pos.to_tuple(("x", "y"))  # (10.0, 20.0)
        """
        if axes is None:
            axes = tuple(self._axes.keys())
        
        return tuple(self._axes.get(axis, 0.0) for axis in axes)
    
    def __getitem__(self, axis: str) -> float:
        """Get axis value by name (case-insensitive)."""
        axis_lower = axis.lower()
        return self._axes.get(axis_lower, 0.0)
    
    def __setitem__(self, axis: str, value: float) -> None:
        """Set axis value by name (case-insensitive)."""
        self._axes[axis.lower()] = float(value)
    
    def __getattr__(self, name: str) -> float:
        """Get axis value as attribute (e.g., pos.x, pos.y)."""
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        return self._axes.get(name.lower(), 0.0)
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Set axis value as attribute (e.g., pos.x = 10)."""
        if name.startswith("_") or name in dir(self):
            super().__setattr__(name, value)
        else:
            if "_axes" in self.__dict__:
                self._axes[name.lower()] = float(value)
            else:
                super().__setattr__(name, value)
    
    def __add__(self, other: Union["Position", Dict[str, float], float]) -> "Position":
        """
        Add two positions or add a scalar to all axes.
        
        Args:
            other: Position, dict, or float to add
        
        Returns:
            New Position instance
        
        Examples:
            >>> pos1 = Position(x=10, y=20)
            >>> pos2 = Position(x=5, y=10)
            >>> pos3 = pos1 + pos2  # Position(x=15, y=30)
            >>> pos4 = pos1 + 5  # Position(x=15, y=25)
        """
        if isinstance(other, Position):
            result = Position()
            all_axes = set(self._axes.keys()) | set(other._axes.keys())
            for axis in all_axes:
                result._axes[axis] = self[axis] + other[axis]
            return result
        elif isinstance(other, dict):
            other_pos = Position.from_dict(other)
            return self + other_pos
        elif isinstance(other, (int, float)):
            result = Position()
            for axis, value in self._axes.items():
                result._axes[axis] = value + other
            return result
        else:
            return NotImplemented
    
    def __radd__(self, other: Union[Dict[str, float], float]) -> "Position":
        """Right-side addition."""
        return self + other
    
    def __sub__(self, other: Union["Position", Dict[str, float], float]) -> "Position":
        """
        Subtract two positions or subtract a scalar from all axes.
        
        Args:
            other: Position, dict, or float to subtract
        
        Returns:
            New Position instance
        
        Examples:
            >>> pos1 = Position(x=10, y=20)
            >>> pos2 = Position(x=5, y=10)
            >>> pos3 = pos1 - pos2  # Position(x=5, y=10)
            >>> pos4 = pos1 - 5  # Position(x=5, y=15)
        """
        if isinstance(other, Position):
            result = Position()
            all_axes = set(self._axes.keys()) | set(other._axes.keys())
            for axis in all_axes:
                result._axes[axis] = self[axis] - other[axis]
            return result
        elif isinstance(other, dict):
            other_pos = Position.from_dict(other)
            return self - other_pos
        elif isinstance(other, (int, float)):
            result = Position()
            for axis, value in self._axes.items():
                result._axes[axis] = value - other
            return result
        else:
            return NotImplemented
    
    def __rsub__(self, other: Union[Dict[str, float], float]) -> "Position":
        """Right-side subtraction."""
        if isinstance(other, dict):
            other_pos = Position.from_dict(other)
            return other_pos - self
        elif isinstance(other, (int, float)):
            result = Position()
            for axis, value in self._axes.items():
                result._axes[axis] = other - value
            return result
        else:
            return NotImplemented
    
    def __mul__(self, scalar: float) -> "Position":
        """
        Multiply all axes by a scalar.
        
        Args:
            scalar: Scalar value to multiply
        
        Returns:
            New Position instance
        
        Examples:
            >>> pos = Position(x=10, y=20)
            >>> pos2 = pos * 2  # Position(x=20, y=40)
        """
        if isinstance(scalar, (int, float)):
            result = Position()
            for axis, value in self._axes.items():
                result._axes[axis] = value * scalar
            return result
        return NotImplemented
    
    def __rmul__(self, scalar: float) -> "Position":
        """Right-side multiplication."""
        return self * scalar
    
    def __truediv__(self, scalar: float) -> "Position":
        """
        Divide all axes by a scalar.
        
        Args:
            scalar: Scalar value to divide by
        
        Returns:
            New Position instance
        
        Examples:
            >>> pos = Position(x=10, y=20)
            >>> pos2 = pos / 2  # Position(x=5, y=10)
        """
        if isinstance(scalar, (int, float)):
            if scalar == 0:
                raise ZeroDivisionError("Cannot divide Position by zero")
            result = Position()
            for axis, value in self._axes.items():
                result._axes[axis] = value / scalar
            return result
        return NotImplemented
    
    def __neg__(self) -> "Position":
        """Negate all axes."""
        result = Position()
        for axis, value in self._axes.items():
            result._axes[axis] = -value
        return result
    
    def __abs__(self) -> "Position":
        """Absolute value of all axes."""
        result = Position()
        for axis, value in self._axes.items():
            result._axes[axis] = abs(value)
        return result
    
    def __eq__(self, other: object) -> bool:
        """Check equality with another Position."""
        if not isinstance(other, Position):
            return False
        return self._axes == other._axes
    
    def __repr__(self) -> str:
        """String representation of Position."""
        if not self._axes:
            return "Position()"
        axis_strs = [f"{k}={v}" for k, v in sorted(self._axes.items())]
        return f"Position({', '.join(axis_strs)})"
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        return self.__repr__()
    
    def get_axes(self) -> Tuple[str, ...]:
        """Get tuple of all axis names."""
        return tuple(sorted(self._axes.keys()))
    
    def has_axis(self, axis: str) -> bool:
        """Check if position has a specific axis."""
        return axis.lower() in self._axes
    
    def copy(self) -> "Position":
        """Create a copy of this Position."""
        return copy.copy(self)

    # swap x and y axes
    def swap_xy(self) -> "Position":
        """Swap x and y axes."""
        self._axes["x"], self._axes["y"] = self._axes["y"], self._axes["x"]
        return self
    
    # get x and y coordinates only
    def get_xy(self) -> "Position":
        """Get x and y coordinates only."""
        return Position(x=self._axes["x"], y=self._axes["y"])