import json
import logging
import os
import time
import uuid
from typing import Dict, List, Any, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Path to store batch job mappings locally as a fallback or for static webhooks
MAPPING_FILE = "config/batch_jobs.json"

class BatchService:
    """
    Service for managing Gemini Batch API requests and mapping callbacks.
    Uses Google AI Studio (Developer API) via GEMINI_API_KEY.
    """

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("Neither GOOGLE_AI_API_KEY nor GEMINI_API_KEY is configured in the environment.")
        self.client = genai.Client(api_key=self.api_key, vertexai=False)
        self._ensure_mapping_file_exists()

    def _ensure_mapping_file_exists(self):
        """Ensure the local batch job mapping file exists"""
        os.makedirs(os.path.dirname(MAPPING_FILE), exist_ok=True)
        if not os.path.exists(MAPPING_FILE):
            with open(MAPPING_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def save_job_mapping(self, batch_job_id: str, user_id: str, metadata: dict) -> None:
        """Save a batch job mapping locally"""
        try:
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            data[batch_job_id] = {
                "user_id": user_id,
                "metadata": metadata,
                "created_at": time.time()
            }
            
            with open(MAPPING_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Saved mapping for batch job {batch_job_id} -> user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save job mapping: {e}", exc_info=True)

    def get_job_mapping(self, batch_job_id: str) -> Optional[dict]:
        """Retrieve a saved batch job mapping"""
        try:
            if not os.path.exists(MAPPING_FILE):
                return None
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get(batch_job_id)
        except Exception as e:
            logger.error(f"Failed to load job mapping: {e}", exc_info=True)
            return None

    def clean_old_jobs(self, max_age_days: int = 7) -> None:
        """Clean up mappings older than max_age_days"""
        try:
            if not os.path.exists(MAPPING_FILE):
                return
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            now = time.time()
            cutoff = now - (max_age_days * 86400)
            
            cleaned_data = {
                k: v for k, v in data.items()
                if v.get("created_at", 0) > cutoff
            }
            
            with open(MAPPING_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to clean old jobs: {e}", exc_info=True)

    def generate_restaurant_analysis_jsonl(self, user_id: str, restaurants: List[Dict[str, Any]]) -> str:
        """
        Generate JSON Lines (JSONL) content for restaurant review analysis.
        Each line asks Gemini to analyze a single restaurant's reviews.
        """
        lines = []
        for idx, rest in enumerate(restaurants):
            name = rest.get("name", "未知餐廳")
            address = rest.get("address", "未知地址")
            rating = rest.get("rating", "未知評分")
            reviews = rest.get("reviews", [])
            
            reviews_text = "\n".join([f"- {rev}" for rev in reviews[:15]])
            
            prompt = f"""請幫我分析以下餐廳的最新用戶評論，並提供深度的美食分析：
餐廳名稱：{name}
地址：{address}
綜合評分：{rating}

用戶評論內容：
{reviews_text}

請用繁體中文回答以下四點（請使用純文字，不要包含任何 markdown 標記如 **、## 或 - 符號）：
1. 餐廳特色與總體口味分析（2句話）
2. 網友高頻推薦的招牌特色菜色與點餐建議
3. 差評或需要注意的雷點/缺點提醒（如排隊太久、服務差、某道菜不好吃）
4. 綜合推薦指數（滿分 5 顆星，給出顆數與簡短理由）
"""
            
            # Request payload format for Gemini Batch API
            # Note: The key should be safe to map back
            request_payload = {
                "key": f"{idx}:{name}",
                "request": {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    "generation_config": {
                        "temperature": 0.5,
                        "max_output_tokens": 1024
                    }
                }
            }
            lines.append(json.dumps(request_payload, ensure_ascii=False))
            
        return "\n".join(lines)

    async def submit_restaurant_batch_job(
        self,
        user_id: str,
        coordinates: Dict[str, float],
        restaurants: List[Dict[str, Any]],
        webhook_domain: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create JSONL, upload it, and submit the Batch Job.
        Configures dynamic webhook if webhook_domain is provided.
        """
        if not restaurants:
            return {"status": "error", "error_message": "沒有提供餐廳資料"}
            
        temp_file_path = f"static/temp_batch_{uuid.uuid4()}.jsonl"
        os.makedirs("static", exist_ok=True)
        
        try:
            # 1. Generate JSONL file locally
            jsonl_content = self.generate_restaurant_analysis_jsonl(user_id, restaurants)
            with open(temp_file_path, "w", encoding="utf-8") as f:
                f.write(jsonl_content)
                
            logger.info(f"Generated temp JSONL file at {temp_file_path}")
            
            # 2. Upload to Gemini File API
            # Files uploaded via standard Client are named 'files/...'
            uploaded_file = self.client.files.upload(
                file=temp_file_path,
                config=types.UploadFileConfig(
                    display_name=f"restaurant_batch_{user_id}_{int(time.time())}",
                    mime_type="application/jsonl"
                )
            )
            logger.info(f"Uploaded JSONL to File API: {uploaded_file.name}")
            
            # Remove temp file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                
            # 3. Submit Batch Job
            webhook_config = None
            if webhook_domain:
                webhook_uri = f"https://{webhook_domain}/api/gemini-callback/dynamic"
                webhook_config = types.WebhookConfig(
                    uris=[webhook_uri],
                    user_metadata={
                        "user_id": user_id,
                        "lat": coordinates.get("latitude"),
                        "lng": coordinates.get("longitude")
                    }
                )
                logger.info(f"Configuring dynamic webhook calling to {webhook_uri}")
            
            config_args = {
                "display_name": f"FoodieAnalysis_{int(time.time())}"
            }
            if webhook_config:
                config_args["webhook_config"] = webhook_config
                
            config = types.CreateBatchJobConfig(**config_args)
            
            job = self.client.batches.create(
                model="gemini-2.5-flash",
                src=uploaded_file.name,
                config=config
            )
            
            # Save mapping locally in case of static webhooks or backup
            self.save_job_mapping(
                batch_job_id=job.name,
                user_id=user_id,
                metadata={
                    "restaurants": [{"name": r.get("name"), "address": r.get("address")} for r in restaurants],
                    "coordinates": coordinates,
                    "file_resource": uploaded_file.name
                }
            )
            
            return {
                "status": "success",
                "batch_job_id": job.name,
                "display_name": job.display_name,
                "state": job.state
            }
            
        except Exception as e:
            logger.error(f"Error submitting batch job: {e}", exc_info=True)
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return {
                "status": "error",
                "error_message": f"建立批次分析工作失敗: {str(e)[:100]}"
            }

    def download_and_parse_batch_results(self, output_file_uri: str) -> List[Dict[str, Any]]:
        """
        Download output JSONL file from Gemini File API and parse it.
        Each line in output is a GenerateContentResponse for a key.
        """
        results = []
        try:
            logger.info(f"Downloading batch results from: {output_file_uri}")
            # output_file_uri is in format 'files/file-id'
            # We can download it using the genai Client
            content_bytes = self.client.files.download_bytes(name=output_file_uri)
            content_str = content_bytes.decode("utf-8")
            
            for line in content_str.strip().split("\n"):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    key = obj.get("key", "")
                    
                    # Split key to get index and restaurant name
                    parts = key.split(":", 1)
                    idx = int(parts[0]) if parts[0].isdigit() else 0
                    rest_name = parts[1] if len(parts) > 1 else key
                    
                    response_obj = obj.get("response", {})
                    # extract candidate text
                    answer = ""
                    if "candidates" in response_obj and response_obj["candidates"]:
                        candidate = response_obj["candidates"][0]
                        if "content" in candidate and "parts" in candidate["content"]:
                            for part in candidate["content"]["parts"]:
                                if "text" in part:
                                    answer += part["text"]
                                    
                    results.append({
                        "index": idx,
                        "name": rest_name,
                        "analysis": answer or "（分析解析失敗）"
                    })
                except Exception as ex:
                    logger.error(f"Failed to parse line in batch result: {ex}")
                    
            # Sort by original index
            results.sort(key=lambda x: x["index"])
            return results
        except Exception as e:
            logger.error(f"Failed to download and parse batch results: {e}", exc_info=True)
            return []
