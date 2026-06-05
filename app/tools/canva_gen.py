import asyncio
import json
import os
import sys

import aiohttp
import aiofiles

GRAPHQL_URL = "https://api.leonardo.ai/v1/graphql"
SCHEMA_VERSION = "1.171.0"
ORIGIN = "https://app.leonardo.ai"

DEFAULT_SESSION_FILE = "session.json"
DEFAULT_IMAGE_PATH = "/Users/chaiyapeng/Downloads//ScreenShot_2026-06-03_150947_318.png"


def load_session(filepath):
    """ session.json  session  accessToken  hasuraUserId."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    session_info = data.get("session", {})
    user_info = data.get("user", {})

    access_token = session_info.get("accessToken", "")
    if not access_token:
        raise RuntimeError("session.json  accessToken")

    hasura_user_id = session_info.get("hasuraUserId", "")
    if not hasura_user_id:
        raise RuntimeError("session.json  hasuraUserId")

    print(f"[Step 0/5]  session.json  token")
    print(f"[Step 0/5]  session.id: {session_info.get('id')}")
    print(f"[Step 0/5]  userId: {session_info.get('userId')}")
    print(f"[Step 0/5]  hasuraUserId: {hasura_user_id}")
    print(f"[Step 0/5]  email: {user_info.get('email')}")
    print(f"[Step 0/5]  name: {user_info.get('name')}")
    print(f"[Step 0/5]  accessToken : {access_token[:60]}...")
    print(f"[Step 0/5]  expiresAt: {session_info.get('expiresAt')}")

    return access_token, hasura_user_id


def build_graphql_headers(token):
    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "origin": ORIGIN,
        "referer": f"{ORIGIN}/",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "x-leo-schema-version": SCHEMA_VERSION,
    }


async def upload_image(image_path, token, hasura_user_id, extension="png"):
    """
    Leonardo.ai :

    Step 1: UploadImage mutation →  S3  URL + fields
    Step 2:  S3
    Step 3: GetInitImageModeration 
    Step 4: GetViewerUploads 

    : {"uploadId": ..., "s3Url": ..., "akUUID": ..., "initImageId": ...}
    """
    headers = build_graphql_headers(token)
    file_name = os.path.basename(image_path)
    file_size = os.path.getsize(image_path)
    print(f"\n[INFO] ========================================")
    print(f"[INFO]  : {file_name}")
    print(f"[INFO]  : {file_size / 1024:.1f} KB")
    print(f"[INFO]  hasuraUserId: {hasura_user_id}")
    print(f"[INFO] ========================================")

    async with aiohttp.ClientSession() as session:
        # 
        # Step 1: UploadImage - 
        # 
        print(f"\n[Step 1/4] UploadImage - ...")
        payload = {
            "operationName": "UploadImage",
            "variables": {
                "uploadImageInput": {
                    "uploadType": "INIT",
                    "extension": extension,
                }
            },
            "query": (
                "mutation UploadImage($uploadImageInput: UploadImageInput!) {\n"
                "  uploadImage(arg1: $uploadImageInput) {\n"
                "    uploadId\n"
                "    url\n"
                "    fields\n"
                "    __typename\n"
                "  }\n"
                "}"
            ),
        }

        async with session.post(GRAPHQL_URL, headers=headers, json=payload) as resp:
            status = resp.status
            raw = await resp.text()
            print(f"[Step 1/4] HTTP {status}")
            if status != 200:
                print(f"[ERROR] : {raw[:500]}")
                raise RuntimeError(f"UploadImage failed: HTTP {status}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[ERROR]  JSON : {raw[:500]}")
                raise

        if data.get("errors"):
            errs = data["errors"]
            print(f"[ERROR] GraphQL : {json.dumps(errs, indent=2)}")
            raise RuntimeError(f"UploadImage GQL error: {errs[0].get('message', 'unknown')}")

        upload_info = data.get("data", {}).get("uploadImage", {})
        upload_id = upload_info.get("uploadId")
        s3_url = upload_info.get("url")
        s3_fields_raw = upload_info.get("fields", {})

        # fields  JSON 
        if isinstance(s3_fields_raw, str):
            s3_fields = json.loads(s3_fields_raw)
        else:
            s3_fields = s3_fields_raw

        print(f"[Step 1/4]  uploadId: {upload_id}")
        print(f"[Step 1/4]  S3 URL: {s3_url}")
        print(f"[Step 1/4]  fields  {len(s3_fields)} :")
        for k, v in s3_fields.items():
            val_str = str(v)
            if len(val_str) > 120:
                val_str = val_str[:120] + "..."
            print(f"[Step 1/4]     {k}: {val_str}")

        # 
        # Step 2:  S3
        # 
        print(f"\n[Step 2/4] S3 ...")
        print(f"[Step 2/4] : {s3_url[:80]}...")

        form_data = aiohttp.FormData()
        for key, value in s3_fields.items():
            form_data.add_field(key, value)

        async with aiofiles.open(image_path, "rb") as f:
            file_data = await f.read()
        print(f"[Step 2/4] : {len(file_data)} bytes")

        form_data.add_field(
            "file",
            file_data,
            filename=file_name,
            content_type=f"image/{extension}",
        )

        s3_headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "origin": ORIGIN,
            "referer": f"{ORIGIN}/",
            "sec-ch-ua": headers["sec-ch-ua"],
            "sec-ch-ua-mobile": headers["sec-ch-ua-mobile"],
            "sec-ch-ua-platform": headers["sec-ch-ua-platform"],
            "user-agent": headers["user-agent"],
        }

        async with session.post(s3_url, data=form_data, headers=s3_headers) as resp:
            s3_status = resp.status
            s3_body = await resp.text()

        if s3_status in (200, 201, 204):
            print(f"[Step 2/4]  S3  HTTP {s3_status}")
        else:
            print(f"[Step 2/4] S3  HTTP {s3_status}: {s3_body[:300]}")

        # 
        # Step 3: GetInitImageModeration - 
        # 
        print(f"\n[Step 3/4] GetInitImageModeration - ...")
        ak_uuid = s3_fields.get("key", "").replace("images/", "").replace(f".{extension}", "")
        print(f"[Step 3/4] akUUID: {ak_uuid}")

        mod_payload = {
            "operationName": "GetInitImageModeration",
            "variables": {"akUUID": ak_uuid},
            "query": (
                "query GetInitImageModeration($akUUID: uuid!) {\n"
                "  init_image_moderation(where: {akUUID: {_eq: $akUUID}}) {\n"
                "    akUUID\n"
                "    initImageId\n"
                "    checkStatus\n"
                "    __typename\n"
                "  }\n"
                "}"
            ),
        }

        init_image_id = None
        for attempt in range(30):
            await asyncio.sleep(2)
            async with session.post(GRAPHQL_URL, headers=headers, json=mod_payload) as resp:
                mod_data = await resp.json()

            mod_list = mod_data.get("data", {}).get("init_image_moderation", [])
            if isinstance(mod_list, list) and mod_list:
                mod_result = mod_list[0]
            else:
                mod_result = mod_list if isinstance(mod_list, dict) else {}

            status = mod_result.get("checkStatus", "PENDING")
            init_image_id = mod_result.get("initImageId") or init_image_id
            print(f"[Step 3/4]    #{attempt + 1}: checkStatus={status}, "
                  f"initImageId={init_image_id}")
            print(f"[Step 3/4]     : {json.dumps(mod_result, ensure_ascii=False)}")

            if status in ("PASSED", "COMPLETED", "Accepted"):
                print(f"[Step 3/4]  ! (status={status})")
                break
        else:
            print(f"[Step 3/4]    (60s)...")

        # 
        # Step 4: GetViewerUploads - 
        # 
        print(f"\n[Step 4/4] GetViewerUploads - ...")
        view_payload = {
            "operationName": "GetViewerUploads",
            "variables": {
                "where": {
                    "userId": {"_eq": hasura_user_id},
                    "teamId": {"_is_null": True},
                },
                "limit": 5,
            },
            "query": (
                "query GetViewerUploads($where: init_images_bool_exp, $limit: Int, $offset: Int) {\n"
                "  init_images(\n"
                "    where: $where\n"
                "    order_by: [{createdAt: desc}, {id: desc}]\n"
                "    limit: $limit\n"
                "    offset: $offset\n"
                "  ) {\n"
                "    id\n"
                "    url\n"
                "    createdAt\n"
                "    generations {\n"
                "      imageWidth\n"
                "      imageHeight\n"
                "      __typename\n"
                "    }\n"
                "    __typename\n"
                "  }\n"
                "}"
            ),
        }

        async with session.post(GRAPHQL_URL, headers=headers, json=view_payload) as resp:
            view_data = await resp.json()

        print(f"[Step 4/4] : {json.dumps(view_data, ensure_ascii=False)[:500]}")
        images = view_data.get("data", {}).get("init_images", [])
        if images:
            latest = images[0]
            print(f"[Step 4/4]  :")
            print(f"[Step 4/4]     id: {latest.get('id')}")
            print(f"[Step 4/4]     url: {latest.get('url', '')[:120]}")
            print(f"[Step 4/4]     createdAt: {latest.get('createdAt')}")
            if latest.get("generations"):
                print(f"[Step 4/4]     : {latest['generations'][0]}")
        else:
            print(f"[Step 4/4]   ")

        result = {
            "uploadId": upload_id,
            "s3Url": s3_url,
            "akUUID": ak_uuid,
            "initImageId": init_image_id,
            "latestUpload": images[0] if images else None,
        }

        print(f"\n[INFO] ========================================")
        print(f"[INFO]   !")
        print(f"[INFO]  uploadId:     {result['uploadId']}")
        print(f"[INFO]  akUUID:       {result['akUUID']}")
        print(f"[INFO]  initImageId:  {result['initImageId']}")
        print(f"[INFO] ========================================")

        return result


async def generate_video(token, hasura_user_id, prompt, image_id,
                         width=496, height=864, duration=15,
                         mode="RESOLUTION_480", motion_has_audio=True,
                         strength="MID", quantity=1, model="seedance-2.0"):
    """
    Leonardo.ai Seedance :

    Step 1: Generate mutation →  generationId
    Step 2: GetAIGenerationFeedStatuses  →  COMPLETE
    Step 3: GetAIGenerationFeed → 

    : {"generationId": ..., "videoUrl": ..., "gifUrl": ..., ...}
    """
    headers = build_graphql_headers(token)
    print(f"\n[INFO] ========================================")
    print(f"[INFO]   ")
    print(f"[INFO]  prompt: {prompt}")
    print(f"[INFO]  imageId: {image_id}")
    print(f"[INFO]  : {width}x{height}, : {duration}s")
    print(f"[INFO]  model: {model}, mode: {mode}")
    print(f"[INFO] ========================================")

    async with aiohttp.ClientSession() as session:
        # 
        # Step 1: Generate - 
        # 
        print(f"\n[Step 1/3] Generate - ...")
        gen_payload = {
            "operationName": "Generate",
            "variables": {
                "request": {
                    "model": model,
                    "public": True,
                    "parameters": {
                        "height": height,
                        "width": width,
                        "duration": duration,
                        "mode": mode,
                        "motion_has_audio": motion_has_audio,
                        "quantity": quantity,
                        "prompt": prompt,
                        "guidances": {
                            "image_reference": [{
                                "image": {"id": image_id, "type": "UPLOADED"},
                                "strength": strength,
                            }]
                        },
                        "seed": -1,
                    }
                }
            },
            "query": (
                "mutation Generate($request: CreateGenerationRequest!) {\n"
                "  generate(request: $request) {\n"
                "    apiCreditCost\n"
                "    generationId\n"
                "    __typename\n"
                "  }\n"
                "}"
            ),
        }

        async with session.post(GRAPHQL_URL, headers=headers, json=gen_payload) as resp:
            status = resp.status
            raw = await resp.text()
            print(f"[Step 1/3] HTTP {status}")
            if status != 200:
                print(f"[ERROR] : {raw[:500]}")
                raise RuntimeError(f"Generate failed: HTTP {status}")
            data = json.loads(raw)

        if data.get("errors"):
            errs = data["errors"]
            print(f"[ERROR] GraphQL : {json.dumps(errs, indent=2)}")
            raise RuntimeError(f"Generate GQL error: {errs[0].get('message', 'unknown')}")

        gen_result = data.get("data", {}).get("generate", {})
        generation_id = gen_result.get("generationId")
        api_cost = gen_result.get("apiCreditCost")
        print(f"[Step 1/3]  generationId: {generation_id}")
        print(f"[Step 1/3]  apiCreditCost: {api_cost}")

        # 
        # Step 2: 
        # 
        print(f"\n[Step 2/3] GetAIGenerationFeedStatuses - ...")
        status_payload = {
            "operationName": "GetAIGenerationFeedStatuses",
            "variables": {
                "where": {
                    "id": {"_in": [generation_id]},
                    "status": {"_in": ["PENDING", "COMPLETE", "FAILED"]},
                }
            },
            "query": (
                "query GetAIGenerationFeedStatuses($where: generations_bool_exp = {}) {\n"
                "  generations(where: $where) {\n"
                "    id\n"
                "    status\n"
                "    __typename\n"
                "  }\n"
                "}"
            ),
        }

        final_status = None
        for attempt in range(60):
            await asyncio.sleep(5)
            async with session.post(GRAPHQL_URL, headers=headers, json=status_payload) as resp:
                s_data = await resp.json()

            gens = s_data.get("data", {}).get("generations", [])
            if gens:
                final_status = gens[0].get("status")
                print(f"[Step 2/3]    #{attempt + 1}: status={final_status}")

            if final_status == "COMPLETE":
                print(f"[Step 2/3]  !")
                break
            elif final_status == "FAILED":
                print(f"[Step 2/3]  !")
                raise RuntimeError(f"Generation FAILED: {generation_id}")
        else:
            print(f"[Step 2/3]    (5min)...")

        # 
        # Step 3: GetAIGenerationFeed - 
        # 
        print(f"\n[Step 3/3] GetAIGenerationFeed - ...")
        feed_payload = {
            "operationName": "GetAIGenerationFeed",
            "variables": {
                "where": {
                    "userId": {"_eq": hasura_user_id},
                    "teamId": {"_is_null": True},
                    "canvasRequest": {"_eq": False},
                    "_and": [
                        {"source": {"_neq": "BLUEPRINTS"}},
                        {"source": {"_neq": "LIGHTNING_STREAM"}},
                        {"universalUpscaler": {"_is_null": True}},
                    ],
                },
                "offset": 0,
                "limit": 20,
            },
            "query": (
                "query GetAIGenerationFeed($where: generations_bool_exp = {}, $limit: Int, $offset: Int = 0) {\n"
                "  generations(\n"
                "    limit: $limit\n"
                "    offset: $offset\n"
                "    order_by: [{createdAt: desc}]\n"
                "    where: $where\n"
                "  ) {\n"
                "    id\n"
                "    createdAt\n"
                "    status\n"
                "    prompt\n"
                "    imageWidth\n"
                "    imageHeight\n"
                "    generation_elements {\n"
                "      id\n"
                "      __typename\n"
                "    }\n"
                "    generated_images(order_by: [{url: desc}]) {\n"
                "      id\n"
                "      url\n"
                "      motionMP4URL\n"
                "      motionGIFURL\n"
                "      image_width\n"
                "      image_height\n"
                "      __typename\n"
                "    }\n"
                "    __typename\n"
                "  }\n"
                "}"
            ),
        }

        async with session.post(GRAPHQL_URL, headers=headers, json=feed_payload) as resp:
            feed_data = await resp.json()

        print(f"[Step 3/3] : {json.dumps(feed_data, ensure_ascii=False)[:800]}")

        gens = feed_data.get("data", {}).get("generations", [])
        video_url = None
        gif_url = None
        image_url = None
        target_gen = None

        for g in gens:
            if g.get("id") == generation_id:
                target_gen = g
                gen_images = g.get("generated_images", [])
                if gen_images:
                    video_url = gen_images[0].get("motionMP4URL")
                    gif_url = gen_images[0].get("motionGIFURL")
                    image_url = gen_images[0].get("url")
                break

        if not target_gen and gens:
            target_gen = gens[0]
            gen_images = target_gen.get("generated_images", [])
            if gen_images:
                video_url = gen_images[0].get("motionMP4URL")
                gif_url = gen_images[0].get("motionGIFURL")
                image_url = gen_images[0].get("url")

        result = {
            "generationId": generation_id,
            "apiCreditCost": api_cost,
            "status": target_gen.get("status") if target_gen else final_status,
            "prompt": target_gen.get("prompt") if target_gen else prompt,
            "videoUrl": video_url,
            "gifUrl": gif_url,
            "imageUrl": image_url,
            "createdAt": target_gen.get("createdAt") if target_gen else None,
        }

        print(f"\n[INFO] ========================================")
        print(f"[INFO]   !")
        print(f"[INFO]  generationId: {result['generationId']}")
        print(f"[INFO]  status:       {result['status']}")
        print(f"[INFO]  videoUrl:     {result['videoUrl']}")
        print(f"[INFO]  gifUrl:       {result['gifUrl']}")
        print(f"[INFO]  imageUrl:     {result['imageUrl']}")
        print(f"[INFO] ========================================")

        return result


async def _async_main():
    session_file = DEFAULT_SESSION_FILE
    image_path = DEFAULT_IMAGE_PATH
    prompt = ""

    if not os.path.exists(session_file):
        print(f"[ERROR] session.json : {session_file}")
        print(f"[HINT]   canva_join.py  session")
        sys.exit(1)
    if not os.path.exists(image_path):
        print(f"[ERROR] : {image_path}")
        sys.exit(1)

    access_token, hasura_user_id = load_session(session_file)

    #  Step A:  
    upload_result = await upload_image(image_path, access_token, hasura_user_id)
    image_id = upload_result.get("initImageId")
    if not image_id:
        print("[ERROR]  initImageId")
        sys.exit(1)

    #  Step B:  
    generate_result = await generate_video(
        token=access_token,
        hasura_user_id=hasura_user_id,
        prompt=prompt,
        image_id=image_id,
    )

    print(f"\n[INFO]  !")
    print(f"[INFO] : initImageId={upload_result['initImageId']}")
    print(f"[INFO] :\n{json.dumps(generate_result, indent=2, ensure_ascii=False)}")


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
