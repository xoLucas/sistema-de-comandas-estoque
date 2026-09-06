import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.routers.auth_deps import require_role
from app.services.backup_service import (
    EXPORTABLE_ENTITIES,
    export_entities_zip,
    export_full_database,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("/entidades")
async def list_entities(
    user: User = Depends(require_role("gerente")),
):
    return [
        {"key": key, "label": _label_for_entity(key)}
        for key in EXPORTABLE_ENTITIES.keys()
    ]


class BackupRequest(BaseModel):
    entities: list[str]


@router.post("/exportar")
async def export_backup(
    req: BackupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    valid_keys = [k for k in req.entities if k in EXPORTABLE_ENTITIES]
    if not valid_keys:
        raise HTTPException(status_code=400, detail="Nenhuma entidade válida selecionada")

    try:
        filename, content = await export_entities_zip(db, valid_keys)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "entities": valid_keys,
    }


@router.post("/exportar-completo")
async def export_complete_backup(
    user: User = Depends(require_role("gerente")),
):
    try:
        filename, content = await export_full_database()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "format": "postgresql-custom",
        "complete": True,
    }


def _label_for_entity(key: str) -> str:
    labels = {
        "produtos": "Produtos",
        "historico_estoque": "Histórico de Estoque",
        "categorias": "Categorias",
        "comandas": "Comandas",
        "itens_comanda": "Itens de Comanda",
        "clientes": "Clientes",
        "funcionarios": "Funcionários",
        "fornecedores": "Fornecedores",
        "consignados": "Consignados",
        "itens_consignados": "Itens de Consignados",
        "pagamentos_consignados": "Pagamentos de Consignados",
        "pagamentos_comandas": "Pagamentos de Comandas",
        "alocacoes_pagamentos_comandas": "Alocações de Pagamentos de Comandas",
        "estornos_pagamentos": "Estornos de Pagamentos",
        "itens_estornos_pagamentos": "Itens de Estornos de Pagamentos",
        "caixa_sessoes": "Sessões de Caixa",
        "caixa_movimentacoes": "Movimentações de Caixa",
        "movimentos_posicao_caixa": "Movimentos da Posição de Caixa",
        "pagamentos_diarias": "Pagamentos de Diárias",
        "despesas": "Despesas",
        "usuarios": "Usuários de Login",
    }
    return labels.get(key, key)
