from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from dependencies import require_admin
from repositories.notice_repo import (
    get_crawl_runs_for_review,
    review_crawl_run,
)
from schemas import CrawlRunReviewRequest


router = APIRouter(prefix="/admin/crawl-runs", tags=["Crawl Admin"])


@router.get("/review-queue")
async def read_crawl_review_queue(
    reviewed: bool = False,
    run_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    admin_id: int = Depends(require_admin),
):
    runs = get_crawl_runs_for_review(
        reviewed=reviewed,
        status=run_status,
        limit=limit,
    )
    return {
        "status": "success",
        "data": runs,
        "count": len(runs),
    }


@router.patch("/{crawl_run_id}/review")
async def update_crawl_run_review(
    crawl_run_id: int,
    request: CrawlRunReviewRequest,
    admin_id: int = Depends(require_admin),
):
    updated = review_crawl_run(
        crawl_run_id,
        reviewer_id=admin_id,
        label=request.label,
        review_notes=request.review_notes,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CRAWL_RUN_NOT_FOUND",
        )
    return {
        "status": "success",
        "crawl_run_id": crawl_run_id,
        "review_label": request.label,
    }
