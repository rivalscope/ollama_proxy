"""
FastAPI Proxy for Ollama with Token Authentication
Supports multiple Ollama instances on different ports
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional, Dict, List
import logging
import json

# Setup logging with debug support
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Set httpx logging level in debug mode
if DEBUG_MODE:
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)
    logger.debug("🐛 DEBUG MODE ENABLED - Full logging active")

app = FastAPI(
    title="Ollama Proxy",
    description="Secure proxy for Ollama instances with token authentication",
    version="1.0.0"
)

# Configuration
API_TOKEN = os.getenv("API_TOKEN", "")
if not API_TOKEN:
    logger.warning("⚠️  API_TOKEN not set! Authentication is disabled.")
else:
    logger.debug(f"🔑 API_TOKEN configured: {API_TOKEN[:4]}...{API_TOKEN[-4:] if len(API_TOKEN) > 8 else '***'}")

# Ollama instances configuration
# Format: "instance_name:host:port,instance_name2:host:port"
# Example: "ollama1:localhost:11434,ollama2:localhost:11435"
OLLAMA_INSTANCES = os.getenv("OLLAMA_INSTANCES", "default:localhost:11434")
logger.debug(f"📝 Raw OLLAMA_INSTANCES config: {OLLAMA_INSTANCES}")

# Parse Ollama instances
def parse_ollama_instances() -> Dict[str, str]:
    instances = {}
    for instance_config in OLLAMA_INSTANCES.split(","):
        parts = instance_config.strip().split(":")
        if len(parts) == 3:
            name, host, port = parts
            instances[name] = f"http://{host}:{port}"
            logger.debug(f"  ➕ Parsed instance '{name}' -> {instances[name]}")
        elif len(parts) == 2:
            # Assume localhost if only name:port given
            name, port = parts
            instances[name] = f"http://localhost:{port}"
            logger.debug(f"  ➕ Parsed instance '{name}' -> {instances[name]} (localhost assumed)")
    return instances

BACKENDS = parse_ollama_instances()
DEFAULT_BACKEND = list(BACKENDS.values())[0] if BACKENDS else "http://localhost:11434"

logger.info(f"📦 Configured backends: {BACKENDS}")
logger.info(f"🎯 Default backend: {DEFAULT_BACKEND}")


async def verify_token(authorization: Optional[str] = Header(None)):
    """Verify the API token from the Authorization header"""
    if not API_TOKEN:
        # If no token is configured, allow all requests (dev mode)
        logger.debug("🔓 No API_TOKEN configured - allowing request")
        return True
    
    if not authorization:
        logger.warning("⛔ Missing Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Support both "Bearer <token>" and just "<token>"
    token = authorization.replace("Bearer ", "").strip()
    logger.debug(f"🔐 Validating token: {token[:4]}...{token[-4:] if len(token) > 8 else '***'}")
    
    if token != API_TOKEN:
        logger.warning("⛔ Invalid authentication token provided")
        raise HTTPException(
            status_code=403,
            detail="Invalid authentication token"
        )
    
    logger.debug("✅ Token validated successfully")
    return True


def get_backend_url(instance_name: Optional[str] = None) -> str:
    """Get the backend URL for the specified instance or default"""
    if instance_name and instance_name in BACKENDS:
        backend = BACKENDS[instance_name]
        logger.debug(f"🎯 Selected backend '{instance_name}': {backend}")
        return backend
    logger.debug(f"🎯 Using default backend: {DEFAULT_BACKEND}")
    return DEFAULT_BACKEND


@app.get("/")
async def root():
    """Health check and information endpoint"""
    return {
        "service": "Ollama Proxy",
        "status": "running",
        "backends": list(BACKENDS.keys()),
        "authentication": "enabled" if API_TOKEN else "disabled"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.api_route("/{instance}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_with_instance(
    instance: str,
    path: str,
    request: Request,
    authenticated: bool = Depends(verify_token)
):
    """
    Proxy requests to specific Ollama instance OR to default if instance name not recognized
    Example: /ollama1/api/tags -> routes to ollama1 backend
    Example: /api/tags -> routes to default backend as /api/tags (if 'api' is not an instance name)
    """
    # Check if the first segment is actually an instance name
    if instance in BACKENDS:
        logger.debug(f"📨 Received request for instance '{instance}', path: {path}")
        backend_url = BACKENDS[instance]
        target_url = f"{backend_url}/{path}"
        return await proxy_request(request, target_url, instance)
    else:
        # Treat the entire path including 'instance' as the path to default backend
        logger.debug(f"📨 '{instance}' is not an instance name, treating as path segment")
        full_path = f"{instance}/{path}" if path else instance
        logger.debug(f"📨 Routing to default backend with full path: {full_path}")
        target_url = f"{DEFAULT_BACKEND}/{full_path}"
        return await proxy_request(request, target_url, "default")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_default(
    path: str,
    request: Request,
    authenticated: bool = Depends(verify_token)
):
    """
    Proxy requests to default Ollama instance
    Example: /api/tags -> routes to default backend
    """
    # Skip root and health endpoints
    if path in ["", "health"]:
        logger.debug(f"📍 Health check endpoint accessed: {path}")
        return {"status": "ok"}
    
    logger.debug(f"📨 Received request for default instance, path: {path}")
    target_url = f"{DEFAULT_BACKEND}/{path}"
    return await proxy_request(request, target_url, "default")


async def proxy_request(request: Request, target_url: str, instance_name: str = "unknown"):
    """
    Forward the request to the target Ollama instance
    Handles both streaming and non-streaming responses
    """
    try:
        # Get request body
        body = await request.body()
        
        # Check if the request is for streaming
        is_stream_request = False
        body_json = None
        if body:
            try:
                body_json = json.loads(body)
                is_stream_request = body_json.get("stream", False)
            except:
                pass
        
        # Log request details in debug mode
        if DEBUG_MODE:
            logger.debug(f"📤 Request details:")
            logger.debug(f"   Method: {request.method}")
            logger.debug(f"   URL: {target_url}")
            logger.debug(f"   Query params: {dict(request.query_params)}")
            logger.debug(f"   Body size: {len(body)} bytes")
            logger.debug(f"   Stream requested: {is_stream_request}")
            if body and len(body) < 1000:  # Only log small bodies
                try:
                    if body_json is None:
                        body_json = json.loads(body)
                    logger.debug(f"   Body: {json.dumps(body_json, indent=2)}")
                except:
                    logger.debug(f"   Body (raw): {body[:200]}...")
        
        # Prepare headers (exclude host and authorization)
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in ["host", "authorization"]
        }
        
        if DEBUG_MODE:
            logger.debug(f"   Headers: {json.dumps(headers, indent=2)}")
        
        logger.info(f"🔄 Proxying {request.method} to '{instance_name}': {target_url}")
        
        # Make the request to Ollama with streaming if needed
        if is_stream_request:
            logger.debug("🌊 Initiating streaming request to Ollama")
            
            # Create a generator that manages its own client and stream
            async def stream_generator():
                chunk_count = 0
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream(
                        method=request.method,
                        url=target_url,
                        content=body,
                        headers=headers,
                        params=request.query_params
                    ) as response:
                        logger.debug(f"📥 Response status: {response.status_code}")
                        logger.debug(f"📥 Response headers: {dict(response.headers)}")
                        
                        # Stream the response immediately
                        async for chunk in response.aiter_bytes():
                            chunk_count += 1
                            if DEBUG_MODE and chunk_count % 10 == 0:
                                logger.debug(f"   Streamed {chunk_count} chunks so far...")
                            yield chunk
                        
                        if DEBUG_MODE:
                            logger.debug(f"✅ Streaming complete: {chunk_count} total chunks")
            
            # Return the streaming response immediately
            return StreamingResponse(
                stream_generator(),
                media_type="application/json"
            )
        
        # Non-streaming path
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Make regular non-streaming request
            response = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers=headers,
                params=request.query_params
            )
            
            logger.debug(f"📥 Response status: {response.status_code}")
            
            # Check if response is streaming (fallback for when stream param is not detected)
            content_type = response.headers.get("content-type", "")
            logger.debug(f"📥 Response content-type: {content_type}")
            logger.debug("📄 Regular response (non-streaming)")
            # Return regular response - pass through the raw content
            try:
                response_data = response.json() if response.text else {}
                if DEBUG_MODE and response.text and len(response.text) < 1000:
                    logger.debug(f"📥 Response body: {json.dumps(response_data, indent=2)}")
            except Exception as e:
                logger.warning(f"⚠️  Could not parse response as JSON: {e}")
                # Return raw text if JSON parsing fails
                response_data = {"raw_response": response.text}
            
            logger.info(f"✅ Request completed successfully: {response.status_code}")
            
            # Filter out hop-by-hop headers
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            }
            
            return JSONResponse(
                content=response_data,
                status_code=response.status_code,
                headers=response_headers
            )
    
    except httpx.ConnectError as e:
        logger.error(f"❌ Connection error to {target_url}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to Ollama backend: {str(e)}"
        )
    except httpx.TimeoutException as e:
        logger.error(f"⏱️  Timeout connecting to {target_url}: {e}")
        raise HTTPException(
            status_code=504,
            detail="Ollama backend timeout"
        )
    except Exception as e:
        logger.error(f"❌ Error proxying request: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Proxy error: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🚀 Starting Ollama Proxy Server")
    logger.info(f"   Host: {host}")
    logger.info(f"   Port: {port}")
    logger.info(f"   Debug: {DEBUG_MODE}")
    logger.info(f"   Log Level: {logging.getLevelName(LOG_LEVEL)}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=DEBUG_MODE,
        log_level="debug" if DEBUG_MODE else "info"
    )
