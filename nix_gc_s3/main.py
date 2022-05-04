import click
import click_log
import boto3
import re
import os
import subprocess
import logging
import itertools
import multiprocessing as mp

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
@click.option("--all-live", is_flag=True, help="consider all keys live")
@click.option("--jobs", type=int, default=1, help="number of parallel jobs")
@click.option("--dry-run", is_flag=True, help="run without delete anything")
@click_log.simple_verbosity_option(logger)
def main(bucket, endpoint, roots, check_missing, all_live, jobs, dry_run):
    s3 = get_s3_client(endpoint)
    cache_info = get_cache_info(s3, bucket)
    store_path = parse_store_path(cache_info)

    keys = set(get_cache_keys(s3, bucket))
    if all_live:
        live_keys = keys
    else:
        live_keys = roots_keys(roots, store_path)
    dead_keys = keys.difference(live_keys)

    if check_missing:
        missing_keys = live_keys.difference(keys)
        for key in sorted(missing_keys):
            logger.info(f"find missing key: {key}")
        if len(missing_keys) != 0:
            exit(1)
    presented_live_keys = keys.intersection(live_keys)
    dangling_keys, dead_nars = get_dead_nars(
        s3, endpoint, bucket, presented_live_keys, jobs
    )
    num_live = len(presented_live_keys) - len(dangling_keys)
    logger.info(
        f"narinfos: all({len(keys)}), live({num_live}), dead({len(dead_keys)}), dangling({len(dangling_keys)})"
    )

    items_to_delete = list(
        itertools.chain(
            map(lambda k: f"{k}.narinfo", dangling_keys),
            dead_nars,
            map(lambda k: f"{k}.narinfo", dead_keys),
        )
    )

    delete_items(s3, bucket, items_to_delete, dry_run)


def get_s3_client(endpoint):
    session = boto3.Session()
    return session.client("s3", endpoint_url=endpoint)


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


def get_dead_nars(s3, endpoint, bucket, live_keys, jobs):
    all_nars = set(get_all_nars(s3, bucket))

    dangling_keys = set()
    live_nars = set()
    results = get_nars(endpoint, bucket, live_keys, jobs)
    for result in results:
        nar_url = result["nar_url"]
        if nar_url not in all_nars:
            dangling_keys.add(result["key"])
        else:
            live_nars.add(nar_url)

    for n in sorted(live_nars):
        logger.debug(f'find live nar "{n}"')

    dead_nars = all_nars.difference(live_nars)

    for n in sorted(dead_nars):
        logger.debug(f'find dead nar "{n}"')

    logger.info(
        f"nars: all({len(all_nars)}), live({len(live_nars)}), dead({len(dead_nars)})"
    )

    return dangling_keys, dead_nars


NARINFO_URL_REGEX = re.compile("^URL: (.*)$", flags=re.MULTILINE)


def get_nars(endpoint, bucket, keys, jobs):
    with mp.Pool(
        jobs, initializer=initialize_download_threads, initargs=(endpoint,)
    ) as pool:
        total = len(keys)

        def build_task(args):
            i, key = args
            return (bucket, key, i, total)

        tasks = map(build_task, enumerate(keys))
        return pool.map(get_nar, tasks)


def initialize_download_threads(endpoint):
    global s3_per_thread
    s3_per_thread = get_s3_client(endpoint)


def get_nar(task):
    bucket, key, i, total = task
    global s3_per_thread
    narinfo = f"{key}.narinfo"
    logger.info(f"[{i + 1:{len(str(total))}}/{total}] fetching {narinfo}...")
    response = s3_per_thread.get_object(Bucket=bucket, Key=narinfo)
    body = response["Body"]
    content = body.read()
    narinfo_content = bytes.decode(content, encoding="utf-8", errors="strict")
    logger.debug(narinfo_content)
    match = NARINFO_URL_REGEX.search(narinfo_content)
    url = match.group(1)
    return {"key": key, "nar_url": url}


def delete_items(s3, bucket, items, dry_run):
    total = len(items)
    for i in range(0, total, 1000):
        logger.info(f"deleting items {i+1}-{min(i + 1000, total)}/{total}...")
        if not dry_run:
            objects = list(map(lambda key: {"Key": key}, items[i : i + 1000]))
            response = s3.delete_objects(
                Bucket=bucket, Delete={"Objects": objects, "Quiet": True}
            )
            logger.debug(response)


if __name__ == "__main__":
    main()
