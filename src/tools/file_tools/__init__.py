"""File tools — all file system operation tools aggregated here."""

from src.tools.file_tools.read_file import read_file
from src.tools.file_tools.write_file import write_file
from src.tools.file_tools.list_directory import list_directory
from src.tools.file_tools.create_directory import create_directory
from src.tools.file_tools.move_file import move_file
from src.tools.file_tools.copy_file import copy_file
from src.tools.file_tools.delete_file import delete_file
from src.tools.file_tools.get_file_info import get_file_info
from src.tools.file_tools.search_files import search_files
from src.tools.file_tools.search_content import search_content
from src.tools.file_tools.change_directory import change_directory

file_tools = [
    change_directory,
    read_file,
    write_file,
    list_directory,
    create_directory,
    move_file,
    copy_file,
    delete_file,
    get_file_info,
    search_files,
    search_content,
]

__all__ = [
    "file_tools",
    "change_directory",
    "read_file",
    "write_file",
    "list_directory",
    "create_directory",
    "move_file",
    "copy_file",
    "delete_file",
    "get_file_info",
    "search_files",
    "search_content",
]
