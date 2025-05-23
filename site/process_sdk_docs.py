#!/usr/bin/env python3

# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import argparse
import os
import os.path as osp
import re
import shutil
import sys
import textwrap
from glob import iglob
from typing import Callable

from inflection import underscore


class Processor:
    _reference_files: list[str]

    def __init__(self, *, input_dir: str, site_root: str) -> None:
        self._input_dir = input_dir
        self._site_root = site_root

        self._content_dir = osp.join(self._site_root, "content")
        self._sdk_reference_dir = osp.join(self._content_dir, "en/docs/api_sdk/sdk/reference")
        self._templates_dir = osp.join(self._site_root, "templates")

    @staticmethod
    def _copy_files(src_dir: str, glob_pattern: str, dst_dir: str) -> list[str]:
        copied_files = []

        for src_path in iglob(osp.join(src_dir, glob_pattern), recursive=True):
            src_filename = osp.relpath(src_path, src_dir)
            dst_path = osp.join(dst_dir, src_filename)
            # assume dst dir exists
            shutil.copy(src_path, dst_path, follow_symlinks=True)

            copied_files.append(dst_path)

        return copied_files

    def _copy_pages(self):
        self._reference_files = self._copy_files(
            self._input_dir, "*/**/*.md", self._sdk_reference_dir
        )

    def _add_page_headers(self):
        """
        Adds headers required by hugo to docs pages
        """

        HEADER_SEPARATOR = "---"

        for p in self._reference_files:
            with open(p) as f:
                contents = f.read()

            assert not contents.startswith(HEADER_SEPARATOR), p

            lines = contents.splitlines()

            assert lines[0].startswith("#")
            classname = lines[0][1:].strip()

            header = textwrap.dedent(
                """\
                %(header_separator)s
                title: '%(classname)s class reference'
                linkTitle: '%(classname)s'
                weight: 10
                description: ''
                %(header_separator)s
            """
                % {"header_separator": HEADER_SEPARATOR, "classname": classname}
            )

            contents = header + "\n".join(lines[1:])

            with open(p, "w") as f:
                f.write(contents)

    def _move_api_summary(self):
        """
        Moves API summary section from README to apis/_index
        """

        SUMMARY_REPLACE_TOKEN = "{{REPLACEME:apis_summary}}"  # nosec

        with open(osp.join(self._input_dir, "api_summary.md")) as f:
            apis_summary = f.read()

        apis_index_filename = osp.join(
            osp.relpath(self._sdk_reference_dir, self._content_dir), "apis/_index.md"
        )
        apis_index_path = osp.join(self._templates_dir, apis_index_filename + ".template")
        with open(apis_index_path) as f:
            contents = f.read()

        contents = contents.replace(SUMMARY_REPLACE_TOKEN, apis_summary)

        with open(osp.join(self._content_dir, apis_index_filename), "w") as f:
            f.write(contents)

    def _fix_page_links_and_references(self):
        """
        Replaces reference page links from full lowercase (which is generated by hugo from the
        original camelcase and creates broken links) ('authapi') to the minus-case ('auth-api'),
        which is more readable and works.
        Adds an extra parent directory part to links ('../') as hugo requires, even for neighbor
        files.
        """

        mapping = {}

        for src_path in self._reference_files:
            src_filename = osp.relpath(src_path, self._sdk_reference_dir)
            dst_filename = underscore(src_filename).replace("_", "-")
            dst_path = osp.join(self._sdk_reference_dir, dst_filename)
            os.rename(src_path, dst_path)
            mapping[src_filename] = dst_filename

        self._reference_files = [osp.join(self._sdk_reference_dir, p) for p in mapping.values()]

        for p in iglob(self._sdk_reference_dir + "/**/*.md", recursive=True):
            with open(p) as f:
                contents = f.read()

            for src_filename, dst_filename in mapping.items():
                src_dir, src_filename = osp.split(osp.splitext(src_filename)[0])
                dst_filename = osp.basename(osp.splitext(dst_filename)[0])
                contents = re.sub(
                    rf"(\[.*?\]\()((?:\.\./)?(?:{src_dir}/)?){src_filename}((?:#[^\)]*?)?\))",
                    rf"\1../\2{dst_filename}\3",
                    contents,
                )

            with open(p, "w") as f:
                f.write(contents)

    def _process_non_code_blocks(self, text: str, handlers: list[Callable[[str], str]]) -> str:
        """
        Allows to process Markdown documents with passed callbacks. Callbacks are only
        executed outside code blocks.
        """

        used_quotes = ""
        block_start_pos = 0
        inside_code_block = False
        while block_start_pos < len(text):
            pattern = re.compile(used_quotes or "```|`")
            next_code_block_quote = pattern.search(text, pos=block_start_pos)
            if next_code_block_quote is not None:
                if not used_quotes:
                    inside_code_block = False
                    block_end_pos = next_code_block_quote.start(0)
                    used_quotes = next_code_block_quote.group(0)
                else:
                    inside_code_block = True
                    block_end_pos = next_code_block_quote.end(0)
                    used_quotes = None
            else:
                block_end_pos = len(text)

            if not inside_code_block:
                block = text[block_start_pos:block_end_pos]

                for handler in handlers:
                    block = handler(block)

                text = text[:block_start_pos] + block + text[block_end_pos:]
                block_end_pos = block_start_pos + len(block) + len(used_quotes)

            block_start_pos = block_end_pos

        return text

    def _escape_free_square_brackets(self, text: str) -> str:
        return re.sub(r"\[([^\[\]]*?)\]([^\(])", r"\[\1\]\2", text)

    def _add_angle_brackets_to_free_links(self, text: str) -> str:
        # Adapted from https://stackoverflow.com/a/31952097
        URL_REGEX = (
            # Scheme (HTTP, HTTPS):
            r"(?:https?:\/\/)"
            r"(?:"
            # www:
            r"(?:www\.)?"
            # Host and domain (including ccSLD):
            r"(?:(?:[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]\.)+)"
            # TLD:
            r"(?:[a-zA-Z]{2,6})"
            # IP Address:
            r"|(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
            r")"
            # Port:
            r"(?::\d{1,5})?"
            # Query path:
            r"(?:(?:\/\S+)*|\/)"
        )

        text = re.sub(
            r"(\A|[\.\s])(" + URL_REGEX + r")([\.\s]|\Z)",
            r"\1<\2>\3",
            text,
            flags=re.MULTILINE,
        )

        return text

    def _fix_parsing_problems(self):
        """
        Adds angle brackets to freestanding links, as the linter requires. Such links can appear
        from the generated model and api descriptions.
        Adds escapes to freestanding square brackets to make parsing correct.
        """

        for p in iglob(self._sdk_reference_dir + "/**/*.md", recursive=True):
            with open(p) as f:
                contents = f.read()

            contents = self._process_non_code_blocks(
                contents,
                [
                    self._add_angle_brackets_to_free_links,
                    self._escape_free_square_brackets,
                ],
            )

            with open(p, "w") as f:
                f.write(contents)

    def run(self):
        assert osp.isdir(self._input_dir), self._input_dir
        assert osp.isdir(self._site_root), self._site_root
        assert osp.isdir(self._sdk_reference_dir), self._sdk_reference_dir
        assert osp.isdir(self._templates_dir), self._templates_dir

        self._copy_pages()
        self._move_api_summary()
        self._add_page_headers()
        self._fix_page_links_and_references()
        self._fix_parsing_problems()


def parse_args(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=osp.abspath,
        default="cvat-sdk/docs/",
        help="Path to the cvat-sdk/docs/ directory",
    )
    parser.add_argument(
        "--site-root",
        type=osp.abspath,
        default="site/",
    )

    return parser.parse_args(args)


def main(args=None):
    args = parse_args(args)
    processor = Processor(input_dir=args.input_dir, site_root=args.site_root)
    processor.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
