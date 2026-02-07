"""
ndi.ido - identifier object class for NDI

This class creates and retrieves unique identifiers. The identifier is a
hexadecimal string based on both the current date/time and a random number.
When identifiers are sorted in alphabetical order, they are also sorted
in the order of time of creation.

Example:
    i = Ido()
    id_value = i.id  # view the id that was created
"""

import time
import random
import re
from typing import Optional


class Ido:
    """NDI identifier object class.

    Creates and stores globally unique IDs based on current time and
    a random number. IDs are sortable by creation time.

    The ID format is: {time_hex}_{random_hex}
    - time_hex: Hexadecimal representation of current time in microseconds
    - random_hex: Random hexadecimal string for uniqueness

    Attributes:
        id (str): The unique identifier string.

    Example:
        >>> ido = Ido()
        >>> print(ido.id)  # prints something like '1a2b3c4d5e6f_7a8b9c0d1e2f'
    """

    def __init__(self, id: Optional[str] = None):
        """Create a new NDI identifier.

        Args:
            id: Optional existing ID string. If not provided, a new
                unique ID is generated automatically.
        """
        if id is not None:
            self._id = id
        else:
            self._id = self.unique_id()

    @property
    def id(self) -> str:
        """Get the identifier string."""
        return self._id

    @staticmethod
    def unique_id() -> str:
        """Generate a new unique ID.

        The ID is constructed from:
        - Current time in microseconds (ensures time-sortability)
        - Random number (ensures uniqueness for same-time IDs)

        Returns:
            A hex string in format: {time_hex}_{random_hex}
        """
        # Get current time in microseconds since epoch
        time_us = int(time.time() * 1000000)
        time_hex = format(time_us, 'x')

        # Generate random component
        random_hex = format(random.getrandbits(48), '012x')

        return f"{time_hex}_{random_hex}"

    @staticmethod
    def is_valid(id_value: str) -> bool:
        """Check if an ID string is a valid NDI ID.

        Valid formats:
        - NDI format: hexstring_hexstring
        - UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

        Args:
            id_value: The ID string to validate.

        Returns:
            True if valid format, False otherwise.
        """
        # Check NDI format (hex_hex)
        ndi_pattern = re.compile(r'^[0-9a-f]+_[0-9a-f]+$', re.I)
        if ndi_pattern.match(str(id_value)):
            return True

        # Also accept UUID format for compatibility
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.I
        )
        if uuid_pattern.match(str(id_value)):
            return True

        return False

    def __repr__(self) -> str:
        return f'Ido({self.id})'

    def __str__(self) -> str:
        return self.id

    def __eq__(self, other) -> bool:
        if isinstance(other, Ido):
            return self.id == other.id
        if isinstance(other, str):
            return self.id == other
        return False

    def __hash__(self) -> int:
        return hash(self.id)
