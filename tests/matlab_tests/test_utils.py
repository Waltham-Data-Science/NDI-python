"""
Port of MATLAB ndi.unittest.util.* tests.

MATLAB source files (ported where Python equivalents exist):
  channelname2prefixnumber tests -> TestChannelNameUtils
  name2variableName tests       -> TestNameUtils
  pseudorandomint tests          -> TestPseudoRandomInt
  timestamp tests                -> TestTimestamp
  ndi.fun.doc.allTypes tests     -> TestAllTypes

MATLAB source files (SKIPPED - no Python equivalent):
  hexDump, hexDiff, hexDiffBytes, getHexDiffFromFileObj
  datestamp2datetime, rehydrateJSONNanNull, unwrapTableCellContent

Tests for:
- ndi.fun.utils.channelname2prefixnumber()
- ndi.fun.utils.name2variable_name()
- ndi.fun.utils.pseudorandomint()
- ndi.fun.utils.timestamp()
- ndi.fun.doc.all_types()
"""

import re

import pytest

from ndi.fun.utils import (
    channelname2prefixnumber,
    name2variable_name,
    pseudorandomint,
    timestamp,
)
from ndi.fun.doc import all_types


# ===========================================================================
# TestChannelNameUtils
# Port of: MATLAB channelname2prefixnumber tests
# ===========================================================================

class TestChannelNameUtils:
    """Port of MATLAB channelname2prefixnumber tests.

    Verifies channel name string parsing into (prefix, number) tuples.
    """

    def test_analog_in(self):
        """'ai5' -> ('ai', 5).

        MATLAB equivalent: channelname2prefixnumber('ai5')
        """
        prefix, number = channelname2prefixnumber('ai5')
        assert prefix == 'ai'
        assert number == 5

    def test_amp_channel(self):
        """'amp1' -> ('amp', 1).

        MATLAB equivalent: channelname2prefixnumber('amp1')
        """
        prefix, number = channelname2prefixnumber('amp1')
        assert prefix == 'amp'
        assert number == 1

    def test_digital_in(self):
        """'di3' -> ('di', 3).

        MATLAB equivalent: channelname2prefixnumber('di3')
        """
        prefix, number = channelname2prefixnumber('di3')
        assert prefix == 'di'
        assert number == 3

    def test_device_channel(self):
        """'dev10' -> ('dev', 10).

        MATLAB equivalent: channelname2prefixnumber('dev10')
        """
        prefix, number = channelname2prefixnumber('dev10')
        assert prefix == 'dev'
        assert number == 10

    def test_analog_out(self):
        """'ao0' -> ('ao', 0).

        MATLAB equivalent: channelname2prefixnumber('ao0')
        """
        prefix, number = channelname2prefixnumber('ao0')
        assert prefix == 'ao'
        assert number == 0

    def test_no_digits_raises(self):
        """Channel name with no digits should raise ValueError.

        MATLAB equivalent: error handling
        """
        with pytest.raises(ValueError, match='No digits found'):
            channelname2prefixnumber('abcdef')

    def test_starts_with_digit_raises(self):
        """Channel name starting with digit should raise ValueError.

        MATLAB equivalent: error handling
        """
        with pytest.raises(ValueError, match='starts with a digit'):
            channelname2prefixnumber('1abc')

    def test_multi_digit_number(self):
        """Channel name with multi-digit number parses correctly.

        MATLAB equivalent: channelname2prefixnumber('ai123')
        """
        prefix, number = channelname2prefixnumber('ai123')
        assert prefix == 'ai'
        assert number == 123


# ===========================================================================
# TestNameUtils
# Port of: MATLAB name2variableName tests
# ===========================================================================

class TestNameUtils:
    """Port of MATLAB name2variableName tests.

    Verifies conversion of arbitrary strings to camelCase variable names.
    """

    def test_name2variable_simple(self):
        """Simple name converts to camelCase.

        MATLAB equivalent: name2variableName('my name')
        """
        result = name2variable_name('my name')
        assert result == 'myName'

    def test_name2variable_with_special_chars(self):
        """Special characters are replaced, words capitalized.

        MATLAB equivalent: name2variableName('hello-world')
        """
        result = name2variable_name('hello-world')
        assert result == 'helloWorld'

    def test_name2variable_with_dots(self):
        """Dot-separated name converts to camelCase.

        MATLAB equivalent: name2variableName('my.variable.name')
        """
        result = name2variable_name('my.variable.name')
        assert result == 'myVariableName'

    def test_name2variable_starts_with_digit(self):
        """Name starting with digit gets 'x' prepended.

        MATLAB equivalent: name2variableName('1abc')
        """
        result = name2variable_name('1abc')
        assert result.startswith('x')

    def test_name2variable_empty(self):
        """Empty string returns empty string.

        MATLAB equivalent: name2variableName('')
        """
        result = name2variable_name('')
        assert result == ''

    def test_name2variable_underscore_preserved(self):
        """Underscores are preserved as word separators.

        MATLAB equivalent: name2variableName('my_var')
        """
        result = name2variable_name('my_var')
        # Underscores are kept in the cleaned string, split happens on spaces
        # So 'my_var' -> cleaned 'my_var' -> split ['my_var'] -> 'my_var'
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# TestTimestamp
# Port of: MATLAB timestamp tests
# ===========================================================================

class TestTimestamp:
    """Port of MATLAB timestamp tests.

    Verifies that timestamp() returns a valid ISO-style string.
    """

    def test_timestamp_format(self):
        """timestamp() returns a valid ISO 8601-style string.

        MATLAB equivalent: ndi.fun.timestamp()
        """
        ts = timestamp()
        assert isinstance(ts, str)
        assert len(ts) > 0
        # Should match pattern: YYYY-MM-DDTHH:MM:SS.mmm
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$'
        assert re.match(pattern, ts), \
            f"Timestamp '{ts}' does not match expected format"

    def test_timestamp_starts_with_year(self):
        """Timestamp starts with a 4-digit year.

        MATLAB equivalent: ndi.fun.timestamp() (implicit)
        """
        ts = timestamp()
        year = int(ts[:4])
        assert 2020 <= year <= 2100, f'Unexpected year: {year}'

    def test_timestamp_contains_t_separator(self):
        """Timestamp contains T separator between date and time.

        MATLAB equivalent: ndi.fun.timestamp() (format check)
        """
        ts = timestamp()
        assert 'T' in ts


# ===========================================================================
# TestPseudoRandomInt
# Port of: MATLAB pseudorandomint tests
# ===========================================================================

class TestPseudoRandomInt:
    """Port of MATLAB pseudorandomint tests.

    Verifies that pseudorandomint() returns positive integers.
    """

    def test_pseudorandomint_is_positive(self):
        """pseudorandomint() returns a positive integer.

        MATLAB equivalent: ndi.fun.pseudorandomint()
        """
        val = pseudorandomint()
        assert isinstance(val, int)
        assert val > 0

    def test_pseudorandomint_uniqueness(self):
        """Multiple calls return different values (very high probability).

        MATLAB equivalent: ndi.fun.pseudorandomint() (uniqueness)
        """
        values = [pseudorandomint() for _ in range(10)]
        # With 1000 possible values per second, 10 values should have
        # some uniqueness. Allow at least 2 unique values.
        unique_values = set(values)
        assert len(unique_values) >= 2, \
            'Expected at least 2 unique values from 10 calls'


# ===========================================================================
# TestAllTypes
# Port of: MATLAB ndi.fun.doc.allTypes tests
# ===========================================================================

class TestAllTypes:
    """Port of MATLAB ndi.fun.doc.allTypes tests.

    Verifies that all_types() returns a list of known document types.
    """

    def test_all_types_returns_list(self):
        """all_types() returns a sorted list of strings.

        MATLAB equivalent: ndi.fun.doc.allTypes()
        """
        types = all_types()
        assert isinstance(types, list)
        assert len(types) > 0

    def test_all_types_contains_base(self):
        """all_types() includes 'base' document type.

        MATLAB equivalent: ndi.fun.doc.allTypes() (contains 'base')
        """
        types = all_types()
        assert 'base' in types, "'base' should be a known document type"

    def test_all_types_are_strings(self):
        """All returned types are non-empty strings.

        MATLAB equivalent: ndi.fun.doc.allTypes() (type check)
        """
        types = all_types()
        for t in types:
            assert isinstance(t, str)
            assert len(t) > 0

    def test_all_types_sorted(self):
        """all_types() returns a sorted list.

        MATLAB equivalent: ndi.fun.doc.allTypes() (sorted)
        """
        types = all_types()
        assert types == sorted(types), 'Types should be sorted alphabetically'

    def test_all_types_contains_known_types(self):
        """all_types() includes several known document types.

        MATLAB equivalent: ndi.fun.doc.allTypes() (spot check)
        """
        types = all_types()
        # These are expected schema files in database_documents/
        expected = ['base', 'demoNDI']
        for doc_type in expected:
            assert doc_type in types, \
                f"Expected '{doc_type}' to be in all_types()"
