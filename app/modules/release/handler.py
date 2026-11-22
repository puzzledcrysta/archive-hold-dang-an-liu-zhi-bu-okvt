from fastapi import APIRouter
from app.inputs import Revision
from . import service

router = APIRouter()


@router.post('/api/release/roster')
def prepare_roster(payload: Revision):
    roster, created = service.prepare(payload)
    return {'created': created, 'roster': roster}


@router.post('/api/release/roster/{roster_id}/switch')
def switch_roster(roster_id: str):
    return service.activate(roster_id)


@router.post('/api/release/rollback')
def rollback_roster():
    return service.restore()


@router.get('/api/release/active')
def active():
    return {'roster': service.current()}


@router.get('/api/release/roster')
def rosters():
    return {'rosters': service.listing()}


@router.get('/api/release/roster/{roster_id}')
def roster_detail(roster_id: str):
    return service.detail(roster_id)


@router.get('/api/release/history')
def roster_history():
    return {'backups': service.backups()}
