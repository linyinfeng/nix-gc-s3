import click
import click_log
import boto3
import tqdm
import re
import os
import subprocess
import logging
from tqdm.contrib.logging import logging_redirect_tqdm

logger = logging.getLogger(__name__)
click_log.basic_config(logger)


@click.command()
@click.argument("bucket")
@click.option("--endpoint", required=True, help="s3 endpoint")
@click.option(
    "--roots",
    multiple=True,
    type=click.Path(exists=True),
    help="directory contains gc roots",
)
@click.option("--check-missing", is_flag=True, help="check missing key")
@click.option("--dry-run", is_flag=True, help="run without delete anything")
@click.option("--progress", is_flag=True, help="show a progress bar")
@click_log.simple_verbosity_option(logger)
def main(bucket, endpoint, roots, check_missing, dry_run, progress):
    s3 = boto3.client("s3", endpoint_url=endpoint)
    cache_info = get_cache_info(s3, bucket)
    store_path = parse_store_path(cache_info)

    keys = set(cache_keys(s3, bucket))
    live_keys = roots_keys(roots, store_path)
    dead_keys = keys.difference(live_keys)

    if check_missing:
        missing_keys = live_keys.difference(keys)
        for key in sorted(missing_keys):
            logger.info(f"find missing key: {key}")
        if len(missing_keys) != 0:
            exit(1)

    for key in sorted(dead_keys):
        logger.info(f'find dead key "{key}"')

    if progress:
        original_handlers = setup_tqdm_logging()
    for item in tqdm.tqdm(
        get_nars(s3, bucket, dead_keys), total=len(dead_keys), disable=not progress
    ):
        # delete nar first
        delete_item(s3, bucket, item["nar"], dry_run)
        delete_item(s3, bucket, item["narinfo"], dry_run)
    if progress:
        restore_tqdm_logging(original_handlers)


# taken from tqdm.contrib.logging
class TqdmLoggingHandler(logging.StreamHandler):
    def __init__(self):
        super(TqdmLoggingHandler, self).__init__()

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.tqdm.write(msg, file=self.stream)
            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


def setup_tqdm_logging():
    original_handlers = logger.handlers  # exactly one handler
    assert len(original_handlers) == 1

    original_handler = original_handlers[0]
    tqdm_handler = TqdmLoggingHandler()
    tqdm_handler.setFormatter(original_handler.formatter)
    logger.handlers = [tqdm_handler]

    return original_handlers


def restore_tqdm_logging(handlers):
    logger.handlers = handlers


def roots_keys(roots, store_path):
    result = set()
    add_roots_keys(roots, store_path, result)
    return result


def add_roots_keys(roots, store_path, result):
    for root in roots:
        add_root_keys(root, store_path, result)


def add_root_keys(root, store_path, result):
    logger.debug(f"root_keys walk path: {root}")

    # follow links for real path
    path = os.path.realpath(root)
    # already a store path
    if path.startswith(store_path):
        add_closure(path, result)
    # a directory
    elif os.path.isdir(path):
        dirs = map(lambda d: d.path, os.scandir(path))
        add_roots_keys(dirs, store_path, result)
    # a regular file
    elif os.path.isfile(path):
        base = os.path.basename(path)
        potential_store_path = os.path.join(store_path, base)
        if os.path.exists(potential_store_path):
            add_closure(potential_store_path, result)


def add_closure(path, result):
    key = parse_key(path)
    # already added
    if key in result:
        return

    query = subprocess.run(
        ["nix-store", "--query", "--requisites", path],
        stdout=subprocess.PIPE,
        check=True,
    )
    stdout = bytes.decode(query.stdout, errors="strict")
    for line in stdout.splitlines():
        key = parse_key(line)
        result.add(key)


STORE_PATH_BASENAME_REGEX = re.compile("^(\w+)-(.*)$")


def parse_key(path):
    base = os.path.basename(path)
    match = STORE_PATH_BASENAME_REGEX.match(base)
    key = match.group(1)
    return key


def get_cache_info(s3, bucket):
    response = s3.get_object(Bucket=bucket, Key="nix-cache-info")
    body = response["Body"]
    content = body.read()
    return bytes.decode(content, encoding="utf-8", errors="strict")


STORE_DIR_REGEX = re.compile("^StoreDir: (.*)$", flags=re.MULTILINE)


def parse_store_path(cache_info_string):
    match = STORE_DIR_REGEX.search(cache_info_string)
    return match.group(1)


def cache_keys(s3, bucket):
    s3_paginator = s3.get_paginator("list_objects_v2")
    suffix = ".narinfo"
    for page in s3_paginator.paginate(Bucket=bucket, Delimiter="/"):
        for content in page.get("Contents", ()):
            key = content["Key"]
            if key.endswith(suffix):
                yield key.removesuffix(suffix)


def get_nars(s3, bucket, keys):
    return map(lambda k: get_nar(s3, bucket, k), keys)


NARINFO_URL_REGEX = re.compile("^URL: (.*)$", flags=re.MULTILINE)


def get_nar(s3, bucket, key):
    narinfo = f"{key}.narinfo"
    response = s3.get_object(Bucket=bucket, Key=narinfo)
    body = response["Body"]
    content = body.read()
    narinfo_content = bytes.decode(content, encoding="utf-8", errors="strict")
    logger.debug(narinfo_content)
    match = NARINFO_URL_REGEX.search(narinfo_content)
    url = match.group(1)
    return {"narinfo": narinfo, "nar": url}


def delete_item(s3, bucket, item, dry_run):
    logger.info(f'deleting "{item}"...')
    if not dry_run:
        response = s3.delete_object(Bucket=bucket, Key=item)
        logger.debug(response)


if __name__ == "__main__":
    main()
