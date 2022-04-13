import click
import click_log
import boto3
import itertools
import re
import os
import subprocess
import logging

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

    keys = set(cache_keys(s3, bucket))
    live_keys = set(roots_keys(roots, store_path))
    dead_keys = keys.difference(live_keys)

    if check_missing:
        missing_keys = live_keys.difference(keys)
        for key in sorted(missing_keys):
            logger.info(f"find missing key: {key}")
        if len(missing_keys) != 0:
            exit(1)

    for key in sorted(dead_keys):
        logger.info(f'find dead key "{key}"')
    dead = get_nars(s3, bucket, dead_keys)

    for item in dead:
        # delete nar first
        delete_item(s3, bucket, item["nar"], dry_run)
        delete_item(s3, bucket, item["narinfo"], dry_run)


def roots_keys(roots, store_path):
    return itertools.chain(*[root_keys(root, store_path) for root in roots])


def root_keys(root, store_path):
    path = os.path.realpath(root)
    logger.debug(f"root_keys walk path: {path}")
    if path.startswith(store_path):
        for key in get_closure(path):
            yield key
    elif os.path.isdir(path):
        dirs = map(lambda d: d.path, os.scandir(path))
        for k in roots_keys(dirs, store_path):
            yield k


STORE_PATH_BASENAME_REGEX = re.compile("^(\w+)-(.*)$")


def get_closure(path):
    query = subprocess.run(
        ["nix-store", "--query", "--requisites", path],
        stdout=subprocess.PIPE,
        check=True,
    )
    stdout = bytes.decode(query.stdout, errors="strict")
    for line in stdout.splitlines():
        yield parse_key(line)


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
