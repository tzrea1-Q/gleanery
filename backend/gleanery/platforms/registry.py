"""按平台取解析器。"""

from __future__ import annotations

from gleanery.platforms.bili import parser as bili_parser
from gleanery.platforms.types import Parser, Platform
from gleanery.platforms.xhs import parser as xhs_parser


def parser_for(platform: Platform) -> Parser:
    return bili_parser.parse if platform == "bili" else xhs_parser.parse
