from fastapi import APIRouter, HTTPException, Depends, status

from repositories.folder_repo import (
    check_folder_depth,
    create_favorite_folder,
    get_favorite_folders_tree,
    update_favorite_folder_name,
    delete_favorite_folder,
    add_notice_to_folder,
    remove_notice_from_folder,
    update_favorite_folder_order,
    add_folder_keyword,
    remove_folder_keyword
)
# 분리해둔 스키마 임포트
from schemas import (
    FolderCreateRequest, 
    FolderRenameRequest, 
    FavoriteNoticeRequest, 
    FolderReorderRequest, 
    KeywordRequest
)

# DB 및 의존성 함수 임포트 (추후 folder_repo.py 등으로 이동할 대상)

from dependencies import get_current_user_id

# APIRouter 객체 생성
# prefix를 "/favorites/folders"로 설정하여 하위 라우터들의 URL 경로를 단축합니다.
router = APIRouter(prefix="/favorites/folders", tags=["Folders"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_folder(
        request: FolderCreateRequest,
        user_id: int = Depends(get_current_user_id)
):
    """새로운 즐겨찾기 폴더를 생성합니다. (2-Depth 제한 적용)"""
    if request.parent_folder_id is not None:
        parent_depth = check_folder_depth(request.parent_folder_id, user_id)
        if parent_depth >= 1:
            raise HTTPException(
                status_code=400,
                detail="폴더는 최대 2단계 하위 폴더까지만 생성할 수 있습니다."
            )

    folder_id = create_favorite_folder(
        user_id=user_id,
        folder_name=request.folder_name,
        parent_folder_id=request.parent_folder_id
    )

    if not folder_id:
        raise HTTPException(status_code=500, detail="폴더 생성에 실패했습니다.")

    return {
        "status": "success",
        "message": "폴더가 생성되었습니다.",
        "folder_id": folder_id
    }


@router.get("")
async def get_folders(user_id: int = Depends(get_current_user_id)):
    """사용자의 전체 즐겨찾기 폴더 트리와 포함된 공지사항을 조회합니다."""
    folders_tree = get_favorite_folders_tree(user_id)
    return {
        "status": "success",
        "data": folders_tree
    }


@router.patch("/{folder_id}")
async def rename_folder(
        folder_id: int,
        request: FolderRenameRequest,
        user_id: int = Depends(get_current_user_id)
):
    """특정 폴더의 이름을 변경합니다."""
    success = update_favorite_folder_name(folder_id, user_id, request.new_folder_name)
    if not success:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없거나 권한이 없습니다.")
    return {"status": "success", "message": "폴더 이름이 변경되었습니다."}


@router.delete("/{folder_id}")
async def delete_folder(
        folder_id: int,
        user_id: int = Depends(get_current_user_id)
):
    """특정 폴더를 삭제합니다. (하위 폴더 및 매핑된 공지사항도 DB의 CASCADE에 의해 자동 삭제됨)"""
    success = delete_favorite_folder(folder_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없거나 권한이 없습니다.")
    return {"status": "success", "message": "폴더가 삭제되었습니다."}


@router.post("/{folder_id}/notices")
async def add_notice_to_favorite(
        folder_id: int,
        request: FavoriteNoticeRequest,
        user_id: int = Depends(get_current_user_id)
):
    """특정 폴더에 공지사항을 추가합니다."""
    success = add_notice_to_folder(folder_id, user_id, request.notice_id)
    if not success:
        raise HTTPException(status_code=400, detail="공지 추가에 실패했습니다. (이미 존재하는 공지이거나 폴더 권한 없음)")
    return {"status": "success", "message": "공지가 즐겨찾기에 추가되었습니다."}


@router.delete("/{folder_id}/notices/{notice_id}")
async def remove_notice_from_favorite(
        folder_id: int,
        notice_id: int,
        user_id: int = Depends(get_current_user_id)
):
    """특정 폴더에서 공지사항을 제거합니다."""
    success = remove_notice_from_folder(folder_id, user_id, notice_id)
    if not success:
        raise HTTPException(status_code=404, detail="매핑 정보를 찾을 수 없거나 권한이 없습니다.")
    return {"status": "success", "message": "공지가 폴더에서 제거되었습니다."}


@router.put("/reorder")
async def update_folder_order(
        request: FolderReorderRequest,
        user_id: int = Depends(get_current_user_id)
):
    """즐겨찾기 폴더의 정렬 순서(sort_order)를 일괄 업데이트합니다."""
    success = update_favorite_folder_order(user_id, request.ordered_folder_ids)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="순서 업데이트에 실패했습니다. 유효하지 않은 폴더이거나 권한이 없습니다."
        )
    return {
        "status": "success",
        "message": "폴더 순서가 성공적으로 업데이트되었습니다."
    }


@router.post("/{folder_id}/keywords", status_code=status.HTTP_201_CREATED)
async def add_keyword(
        folder_id: int,
        request: KeywordRequest,
        user_id: int = Depends(get_current_user_id)
):
    """특정 폴더에 자동 분류를 위한 새로운 키워드를 추가합니다."""
    keyword = request.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="키워드는 빈 값일 수 없습니다.")

    success = add_folder_keyword(folder_id, user_id, keyword)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="키워드 추가에 실패했습니다. (권한 없음 또는 중복된 키워드)"
        )
    return {
        "status": "success",
        "message": f"키워드 '{keyword}'가 추가되었습니다."
    }


@router.delete("/{folder_id}/keywords/{keyword}")
async def delete_keyword(
        folder_id: int,
        keyword: str,
        user_id: int = Depends(get_current_user_id)
):
    """특정 폴더에서 키워드를 삭제합니다."""
    success = remove_folder_keyword(folder_id, user_id, keyword)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="해당 키워드를 찾을 수 없거나 삭제할 권한이 없습니다."
        )
    return {
        "status": "success",
        "message": f"키워드 '{keyword}'가 삭제되었습니다."
    }