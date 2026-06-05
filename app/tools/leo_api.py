"""Leonardo.ai API — 所有请求日志均为中文详细输出."""

import asyncio
import json
import os

import aiohttp
import aiofiles

GRAPHQL_URL = "https://api.leonardo.ai/v1/graphql"
SCHEMA_VERSION = "1.171.0"
ORIGIN = "https://app.leonardo.ai"
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 1200


def build_graphql_headers(token):
    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "origin": ORIGIN,
        "referer": f"{ORIGIN}/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "x-leo-schema-version": SCHEMA_VERSION,
    }


# ═══════════════════════════════════════════════════════════
#  同步封装
# ═══════════════════════════════════════════════════════════


def get_user_details_sync(access_token, user_sub):
    """查询用户详情（积分、plan 等）."""
    return asyncio.run(_get_user_details(access_token, user_sub))


def upload_image_sync(image_path, token, hasura_user_id, extension="png"):
    """上传图片到 Leonardo."""
    return asyncio.run(_upload_image(image_path, token, hasura_user_id, extension))


def submit_generation_sync(token, hasura_user_id, prompt, image_id, **kwargs):
    """提交视频生成任务，返回 generationId."""
    return asyncio.run(_submit_generation(token, hasura_user_id, prompt, image_id, **kwargs))


def poll_generation_sync(token, hasura_user_id, generation_id, cancel_event=None):
    """轮询生成状态并获取结果 URL."""
    return asyncio.run(_poll_generation(token, hasura_user_id, generation_id, cancel_event))


# ═══════════════════════════════════════════════════════════
#  异步实现
# ═══════════════════════════════════════════════════════════


async def _get_user_details(access_token, user_sub):
    """查询用户详情."""
    headers = build_graphql_headers(access_token)
    payload = {
        "operationName": "GetUserDetails",
        "variables": {"userSub": user_sub},
        "query": (
            "query GetUserDetails($userSub: String) {\n"
            "  users(where: {user_details: {cognitoId: {_eq: $userSub}}}) {\n"
            "    id\n"
            "    username\n"
            "    user_details {\n"
            "      id\n"
            "      apiConcurrencySlots\n"
            "      apiCredit\n"
            "      plan\n"
            "      subscriptionTokens\n"
            "      subscriptionModelTokens\n"
            "      subscriptionSource\n"
            "      tokenRenewalDate\n"
            "      paidTokens\n"
            "      rolloverTokens\n"
            "      __typename\n"
            "    }\n"
            "    __typename\n"
            "  }\n"
            "}"
        ),
    }

    print(f"  [查询积分] 请求中... sub={user_sub[:16]}...")
    async with aiohttp.ClientSession() as session:
        async with session.post(GRAPHQL_URL, headers=headers, json=payload) as resp:
            data = await resp.json()
    print(f"  [查询积分] HTTP {resp.status}")

    if data.get("errors"):
        err_msg = data["errors"][0].get("message", "未知错误")
        # token 过期通常返回 authorization 相关错误
        if "auth" in err_msg.lower() or "token" in err_msg.lower() or "jwt" in err_msg.lower():
            raise RuntimeError(f"Token已过期或无效: {err_msg}")
        raise RuntimeError(f"查询失败: {err_msg}")

    users = data.get("data", {}).get("users", [])
    if not users:
        # 大概率是 token 过期 → 返回空用户 (积分=0)
        print(f"  [查询积分] ⚠ 未找到用户，token可能已过期")
        return {"username": "?", "user_details": [{"subscriptionTokens": 0, "plan": "EXPIRED"}]}

    details = users[0].get("user_details", [{}])[0] if users[0].get("user_details") else {}
    username = users[0].get("username", "?")
    tokens = details.get("subscriptionTokens", 0)
    plan = details.get("plan", "?")
    print(f"  [查询积分] 用户={username} plan={plan} 积分={tokens}")
    return users[0]


async def _upload_image(image_path, token, hasura_user_id, extension="png"):
    """上传图片：获取预签名 URL → 上传 S3 → 等待审核."""
    headers = build_graphql_headers(token)
    file_name = os.path.basename(image_path)
    file_size = os.path.getsize(image_path)
    print(f"  [上传图片] 文件={file_name} 大小={file_size / 1024:.1f} KB")

    async with aiohttp.ClientSession() as session:
        # Step 1: 获取预签名 URL
        payload = {
            "operationName": "UploadImage",
            "variables": {"uploadImageInput": {"uploadType": "INIT", "extension": extension}},
            "query": (
                "mutation UploadImage($uploadImageInput: UploadImageInput!) {\n"
                "  uploadImage(arg1: $uploadImageInput) {\n"
                "    uploadId\n    url\n    fields\n    __typename\n  }\n}"
            ),
        }
        async with session.post(GRAPHQL_URL, headers=headers, json=payload) as resp:
            data = await resp.json()
        if data.get("errors"):
            raise RuntimeError(f"获取上传URL失败: {data['errors'][0]['message']}")

        info = data["data"]["uploadImage"]
        s3_url = info["url"]
        s3_fields = info["fields"]
        if isinstance(s3_fields, str):
            s3_fields = json.loads(s3_fields)
        print(f"  [上传图片] 已获取预签名URL uploadId={info['uploadId']}")

        # Step 2: 上传到 S3
        form = aiohttp.FormData()
        for k, v in s3_fields.items():
            form.add_field(k, v)
        async with aiofiles.open(image_path, "rb") as f:
            file_data = await f.read()
        form.add_field("file", file_data, filename=file_name, content_type=f"image/{extension}")
        async with session.post(s3_url, data=form) as resp:
            print(f"  [上传图片] S3上传 HTTP {resp.status}")
        if resp.status >= 400:
            raise RuntimeError(f"S3上传失败 HTTP {resp.status}")

        # Step 3: 等待审核
        ak_uuid = s3_fields.get("key", "").replace("images/", "").replace(f".{extension}", "")
        mod_payload = {
            "operationName": "GetInitImageModeration",
            "variables": {"akUUID": ak_uuid},
            "query": (
                "query GetInitImageModeration($akUUID: uuid!) {\n"
                "  init_image_moderation(where: {akUUID: {_eq: $akUUID}}) {\n"
                "    akUUID\n    initImageId\n    checkStatus\n    __typename\n  }\n}"
            ),
        }
        init_image_id = None
        for i in range(30):
            await asyncio.sleep(2)
            async with session.post(GRAPHQL_URL, headers=headers, json=mod_payload) as resp:
                mod_data = await resp.json()
            mods = mod_data.get("data", {}).get("init_image_moderation", [])
            if isinstance(mods, list) and mods:
                m = mods[0]
            else:
                m = mods if isinstance(mods, dict) else {}
            status = m.get("checkStatus", "PENDING")
            init_image_id = m.get("initImageId") or init_image_id
            if i == 0:
                print(f"  [上传图片] 等待审核... (初始状态={status})")
            if status in ("PASSED", "COMPLETED", "Accepted"):
                print(f"  [上传图片] 审核通过 (第{i + 1}次查询) initImageId={init_image_id}")
                break
        else:
            raise RuntimeError(f"图片审核超时 (akUUID={ak_uuid})")

        return {"uploadId": info["uploadId"], "akUUID": ak_uuid, "initImageId": init_image_id}


async def _submit_generation(token, hasura_user_id, prompt, image_id,
                              width=496, height=864, duration=15,
                              mode="RESOLUTION_480", motion_has_audio=True,
                              strength="MID", quantity=1, model="seedance-2.0"):
    """提交视频生成任务，立即返回 generationId."""
    headers = build_graphql_headers(token)
    prompt_short = prompt[:40] + "..." if len(prompt) > 40 else prompt
    print(f"  [提交生成] prompt=\"{prompt_short}\" imageId={image_id} model={model} {width}x{height} {duration}s")

    async with aiohttp.ClientSession() as session:
        gen_payload = {
            "operationName": "Generate",
            "variables": {
                "request": {
                    "model": model,
                    "public": True,
                    "parameters": {
                        "height": height, "width": width, "duration": duration,
                        "mode": mode, "motion_has_audio": motion_has_audio,
                        "quantity": quantity, "prompt": prompt,
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
                "    apiCreditCost\n    generationId\n    __typename\n  }\n}"
            ),
        }
        async with session.post(GRAPHQL_URL, headers=headers, json=gen_payload) as resp:
            data = await resp.json()
        print(f"  [提交生成] HTTP {resp.status}")

        if data.get("errors"):
            raise RuntimeError(f"提交生成失败: {data['errors'][0]['message']}")

        gen = data["data"]["generate"]
        generation_id = gen["generationId"]
        cost = gen["apiCreditCost"]
        print(f"  [提交生成] ✓ 成功 generationId={generation_id} 消耗积分={cost}")
        return {"generationId": generation_id, "apiCreditCost": cost}


async def _poll_generation(token, hasura_user_id, generation_id, cancel_event=None):
    """轮询生成状态 → 获取视频 URL."""
    headers = build_graphql_headers(token)
    print(f"  [轮询结果] generationId={generation_id} 开始轮询...")

    async with aiohttp.ClientSession() as session:
        # Step 1: 轮询状态
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
                "  generations(where: $where) {\n    id\n    status\n    __typename\n  }\n}"
            ),
        }
        final_status = None
        max_attempts = POLL_TIMEOUT_SECONDS // POLL_INTERVAL_SECONDS
        for i in range(max_attempts):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

            # 检查取消
            if cancel_event and cancel_event.is_set():
                print(f"  [轮询结果] ⚠ 用户取消 (第{i + 1}次查询)")
                raise RuntimeError("轮询已被用户取消")

            async with session.post(GRAPHQL_URL, headers=headers, json=status_payload) as resp:
                s_data = await resp.json()
            gens = s_data.get("data", {}).get("generations", [])
            if gens:
                final_status = gens[0].get("status")
                elapsed = (i + 1) * POLL_INTERVAL_SECONDS
                status_cn = {"PENDING": "排队中", "COMPLETE": "已完成", "FAILED": "失败"}.get(final_status, final_status)
                if i == 0 or final_status != "PENDING" or elapsed % 60 == 0:
                    print(f"  [轮询结果] 第{i + 1}次({elapsed}s) 状态={status_cn}")
            if final_status == "COMPLETE":
                print(f"  [轮询结果] ✓ 生成完成 总耗时={elapsed}s")
                break
            elif final_status == "FAILED":
                raise RuntimeError(f"视频生成失败 generationId={generation_id}")
        else:
            raise RuntimeError(f"轮询超时 ({POLL_TIMEOUT_SECONDS}s) generationId={generation_id} 最后状态={final_status}")

        # Step 2: 获取结果 URL
        print(f"  [轮询结果] 获取视频URL...")
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
                "offset": 0, "limit": 20,
            },
            "query": (
                "query GetAIGenerationFeed($where: generations_bool_exp = {}, $limit: Int, $offset: Int = 0) {\n"
                "  generations(limit: $limit, offset: $offset, order_by: [{createdAt: desc}], where: $where) {\n"
                "    id\n    createdAt\n    status\n    prompt\n"
                "    generated_images(order_by: [{url: desc}]) {\n"
                "      id\n      url\n      motionMP4URL\n      motionGIFURL\n"
                "      image_width\n      image_height\n      __typename\n    }\n"
                "    __typename\n  }\n}"
            ),
        }
        async with session.post(GRAPHQL_URL, headers=headers, json=feed_payload) as resp:
            feed_data = await resp.json()

        gens = feed_data.get("data", {}).get("generations", [])
        video_url = gif_url = image_url = None
        for g in gens:
            if g.get("id") == generation_id:
                imgs = g.get("generated_images", [])
                if imgs:
                    video_url = imgs[0].get("motionMP4URL")
                    gif_url = imgs[0].get("motionGIFURL")
                    image_url = imgs[0].get("url")
                break

        if video_url:
            print(f"  [轮询结果] ✓ 视频URL已获取")
        else:
            print(f"  [轮询结果] ⚠ 未找到视频URL (generationId={generation_id})")

        result = {
            "generationId": generation_id,
            "status": final_status,
            "videoUrl": video_url,
            "gifUrl": gif_url,
            "imageUrl": image_url,
        }
        return result
