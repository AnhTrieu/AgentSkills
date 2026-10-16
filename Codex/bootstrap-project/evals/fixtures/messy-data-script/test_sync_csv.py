from unittest.mock import Mock, patch
from sync_csv import sync_csv


def test_returns_row_count_without_live_database():
    rows = Mock()
    rows.__len__ = Mock(return_value=2)
    with patch('sync_csv.pd.read_csv', return_value=rows), patch('sync_csv.create_engine'):
        assert sync_csv('example.csv', 'sqlite://') == 2
