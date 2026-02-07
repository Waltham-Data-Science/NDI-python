"""
ndi.time.timemapping - Time mapping class for NDI framework.

This module provides the TimeMapping class for managing mapping of time
across epochs and devices using polynomial transformations.
"""

from __future__ import annotations
from typing import Union, List, Sequence
import numpy as np


class TimeMapping:
    """
    Class for managing mapping of time across epochs and devices.

    Describes mapping from one time base to another using a polynomial.
    The property `mapping` is a vector of length N+1 that describes the
    coefficients of a polynomial such that:

        t_out = mapping[0]*t_in^N + mapping[1]*t_in^(N-1) + ... + mapping[N]

    Usually, one specifies a linear relationship only, with mapping = [scale, shift]
    so that:

        t_out = scale * t_in + shift

    Example:
        >>> tm = TimeMapping([1, 0])  # Identity mapping
        >>> tm.map(5.0)
        5.0
        >>> tm = TimeMapping([2, 10])  # t_out = 2*t_in + 10
        >>> tm.map(5.0)
        20.0
    """

    def __init__(self, mapping: Union[List[float], np.ndarray, None] = None):
        """
        Create a new TimeMapping object.

        Args:
            mapping: Polynomial coefficients [a_n, a_{n-1}, ..., a_1, a_0]
                    where t_out = a_n*t^n + a_{n-1}*t^{n-1} + ... + a_1*t + a_0.
                    Default is [1, 0] (identity mapping).

        Raises:
            ValueError: If mapping test with t_in=0 fails
        """
        if mapping is None:
            mapping = [1.0, 0.0]

        self._mapping = np.asarray(mapping, dtype=float)

        # Test the mapping
        try:
            self.map(0.0)
        except Exception as e:
            raise ValueError(f"Mapping test with t_in=0 failed: {e}")

    @property
    def mapping(self) -> np.ndarray:
        """Get the polynomial coefficients."""
        return self._mapping

    @property
    def scale(self) -> float:
        """
        Get the scale factor (for linear mappings).

        For a linear mapping [scale, shift], returns the scale.
        For higher-order polynomials, returns the first coefficient.
        """
        return float(self._mapping[0])

    @property
    def shift(self) -> float:
        """
        Get the shift/offset (for linear mappings).

        For a linear mapping [scale, shift], returns the shift.
        For higher-order polynomials, returns the last coefficient.
        """
        return float(self._mapping[-1])

    def map(self, t_in: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """
        Perform a mapping from one time base to another.

        Args:
            t_in: Input time value(s)

        Returns:
            Output time value(s) after applying the polynomial mapping
        """
        return np.polyval(self._mapping, t_in)

    def __call__(self, t_in: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Allow calling the mapping directly like a function."""
        return self.map(t_in)

    @classmethod
    def identity(cls) -> 'TimeMapping':
        """
        Create an identity mapping (t_out = t_in).

        Returns:
            TimeMapping with [1, 0] coefficients
        """
        return cls([1.0, 0.0])

    @classmethod
    def linear(cls, scale: float = 1.0, shift: float = 0.0) -> 'TimeMapping':
        """
        Create a linear mapping: t_out = scale * t_in + shift.

        Args:
            scale: Scale factor (default 1.0)
            shift: Offset/shift (default 0.0)

        Returns:
            TimeMapping with [scale, shift] coefficients
        """
        return cls([scale, shift])

    def inverse(self) -> 'TimeMapping':
        """
        Compute the inverse mapping (for linear mappings only).

        For t_out = scale * t_in + shift, the inverse is:
        t_in = (1/scale) * t_out - shift/scale

        Returns:
            TimeMapping representing the inverse transformation

        Raises:
            ValueError: If mapping is not linear or scale is zero
        """
        if len(self._mapping) != 2:
            raise ValueError("Inverse only supported for linear mappings")
        if self._mapping[0] == 0:
            raise ValueError("Cannot invert mapping with zero scale")

        inv_scale = 1.0 / self._mapping[0]
        inv_shift = -self._mapping[1] / self._mapping[0]
        return TimeMapping([inv_scale, inv_shift])

    def compose(self, other: 'TimeMapping') -> 'TimeMapping':
        """
        Compose two mappings: apply self first, then other.

        For linear mappings:
        self:  t1 = a*t0 + b
        other: t2 = c*t1 + d

        Result: t2 = c*(a*t0 + b) + d = (c*a)*t0 + (c*b + d)

        Args:
            other: The mapping to apply after this one

        Returns:
            Composed TimeMapping

        Raises:
            ValueError: If either mapping is not linear
        """
        if len(self._mapping) != 2 or len(other._mapping) != 2:
            raise ValueError("Compose only supported for linear mappings")

        a, b = self._mapping
        c, d = other._mapping

        new_scale = c * a
        new_shift = c * b + d

        return TimeMapping([new_scale, new_shift])

    def __eq__(self, other: object) -> bool:
        """Check equality of two time mappings."""
        if not isinstance(other, TimeMapping):
            return NotImplemented
        return np.allclose(self._mapping, other._mapping)

    def __repr__(self) -> str:
        """Return string representation."""
        if len(self._mapping) == 2:
            return f"TimeMapping(scale={self.scale}, shift={self.shift})"
        return f"TimeMapping({list(self._mapping)})"

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary with 'mapping' key
        """
        return {'mapping': self._mapping.tolist()}

    @classmethod
    def from_dict(cls, data: dict) -> 'TimeMapping':
        """
        Create TimeMapping from dictionary.

        Args:
            data: Dictionary with 'mapping' key

        Returns:
            TimeMapping instance
        """
        return cls(data['mapping'])
