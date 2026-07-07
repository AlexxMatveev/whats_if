from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import List
import json

from app.manifest_parser import parse_manifests, manifest_to_normatives

router = APIRouter(prefix="/api", tags=["manifest"])


@router.post("/manifest/parse")
async def parse_manifest(files: List[UploadFile] = File(...)):
    texts = []
    for f in files:
        content = await f.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("cp1251")
            except UnicodeDecodeError:
                raise HTTPException(status_code=400, detail=f"Cannot decode file: {f.filename}")
        texts.append(text)

    try:
        result = parse_manifests(texts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Parse error: {str(e)}")

    normatives = manifest_to_normatives(result)

    # Build response
    apps_out = []
    for app in result.apps:
        apps_out.append({
            "name": app.name,
            "replicas": app.replicas,
            "cpu_request": app.cpu_request,
            "cpu_limit": app.cpu_limit,
            "mem_request": app.mem_request,
            "mem_limit": app.mem_limit,
            "hpa_cpu_target": app.hpa_cpu_target,
            "service_ports": app.service_ports,
            "ingress_paths": app.ingress_paths,
        })

    return {
        "apps": apps_out,
        "ingress_hosts": result.ingress_hosts,
        "normatives": normatives,
    }
