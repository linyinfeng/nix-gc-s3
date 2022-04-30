import click
import click_log
import boto3
import re
import os
import subprocess
import logging
import itertools

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
@click_log.simple_verbosity_option(logger)
def main(bucket, endpoint, roots, check_missing, dry_run):
    s3 = boto3.client("s3", endpoint_url=endpoint)
    cache_info = get_cache_info(s3, bucket)
    store_path = parse_store_path(cache_info)

    keys = set(get_cache_keys(s3, bucket))
    live_keys = roots_keys(roots, store_path)
    dead_keys = keys.difference(live_keys)

    if check_missing:
        missing_keys = live_keys.difference(keys)
        for key in sorted(missing_keys):
            logger.info(f"find missing key: {key}")
        if len(missing_keys) != 0:
            exit(1)
    presented_live_keys = keys.intersection(live_keys)

    for key in sorted(dead_keys):
        logger.info(f'find dead key "{key}"')

    dead_nars = get_dead_nars(s3, bucket, presented_live_keys)
    items_to_delete = list(
        itertools.chain(dead_nars, map(lambda k: f"{k}.narinfo", dead_keys))
    )

    total = len(items_to_delete)
    for i, item in enumerate(items_to_delete):
        logger.info(f'[{i:{len(str(total))}}/{total}] deleting "{item}"...')
        delete_item(s3, bucket, item, dry_run)


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


def get_cache_keys(s3, bucket):
    s3_paginator = s3.get_paginator("list_objects_v2")
    suffix = ".narinfo"
    for page in s3_paginator.paginate(Bucket=bucket, Delimiter="/"):
        for content in page.get("Contents", ()):
            key = content["Key"]
            if key.endswith(suffix):
                yield key.removesuffix(suffix)


def get_all_nars(s3, bucket):
    s3_paginator = s3.get_paginator("list_objects_v2")
    for page in s3_paginator.paginate(Bucket=bucket, Prefix="nar/", Delimiter="/"):
        for content in page.get("Contents", ()):
            yield content["Key"]


def get_dead_nars(s3, bucket, live_keys, progress=None):
    all_nars = set(get_all_nars(s3, bucket))

    live_nars = set()
    total = len(live_keys)
    for i, k in enumerate(live_keys):
        logger.info(f'[{i:{len(str(total))}}/{total}] fetching "{k}.narinfo"...')
        live_nars.add(get_nar(s3, bucket, k))

    dead_nars = all_nars.difference(live_nars)
    return dead_nars


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
    return url


def delete_item(s3, bucket, item, dry_run):
    if not dry_run:
        response = s3.delete_object(Bucket=bucket, Key=item)
        logger.debug(response)


if __name__ == "__main__":
    main()
