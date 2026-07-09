"""
Campaign Express Number Allocator Service
Handles automatic assignment of platform-owned pool numbers to CE campaigns.

Assignment Strategies:
  1. SINGLE: If only one active number → always use that number
  2. ROUND_ROBIN: Cycle through all active numbers sequentially
  3. LEAST_LOADED: Assign to number with fewest active_campaigns_count
  4. FALLBACK: If all numbers are at capacity → queue and wait for release

CE users never see, choose, or interact with these numbers.
All allocation is invisible and internal.
"""
import logging
from datetime import datetime
from app.extensions import db
from app.models.ce_number_pool import CeNumberPool, CeCampaignNumberAssignment

logger = logging.getLogger(__name__)


class CeNumberAllocator:
    """
    Service for allocating platform-owned CE pool numbers to campaigns.
    Call `allocate(campaign_id)` before starting execution.
    Call `release(campaign_id)` after campaign ends (success or failure).
    """

    @staticmethod
    def get_active_pool():
        """Return all active, healthy numbers in the pool."""
        return CeNumberPool.query.filter_by(is_active=True, is_healthy=True).all()

    @staticmethod
    def allocate(campaign_id: int) -> CeNumberPool | None:
        """
        Assign a pool number to a campaign using the best available strategy.

        Returns:
            CeNumberPool  if a number was successfully assigned.
            None          if no numbers are available (campaign should be queued).
        """
        pool = CeNumberAllocator.get_active_pool()

        if not pool:
            logger.warning(
                "CE Number Allocator: No active numbers in pool for campaign %s", campaign_id
            )
            return None

        # ── Strategy 1: Only one number → use it ─────────────────────────────
        if len(pool) == 1:
            selected = pool[0]

        # ── Strategy 2: Multiple numbers → least loaded ───────────────────────
        else:
            selected = min(pool, key=lambda n: n.active_campaigns_count)

        # ── Record the assignment ─────────────────────────────────────────────
        existing = CeCampaignNumberAssignment.query.filter_by(
            campaign_id=campaign_id, status="active"
        ).first()
        if existing:
            # Already assigned — return the existing number
            return existing.pool_number

        assignment = CeCampaignNumberAssignment(
            campaign_id    = campaign_id,
            pool_number_id = selected.id,
            status         = "active",
        )
        db.session.add(assignment)

        # Increment load counter
        selected.active_campaigns_count = (selected.active_campaigns_count or 0) + 1
        selected.total_campaigns_served = (selected.total_campaigns_served or 0) + 1
        selected.last_used_at           = datetime.utcnow()

        db.session.commit()

        logger.info(
            "CE Number Allocator: campaign %s → number '%s' (%s)",
            campaign_id, selected.label, selected.number,
        )
        return selected

    @staticmethod
    def release(campaign_id: int) -> bool:
        """
        Release the number assigned to a campaign back to the pool.
        Called after campaign completes, fails, or is terminated.

        Returns:
            True if successfully released, False if no assignment found.
        """
        assignment = CeCampaignNumberAssignment.query.filter_by(
            campaign_id=campaign_id, status="active"
        ).first()

        if not assignment:
            logger.debug(
                "CE Number Allocator: No active assignment found for campaign %s", campaign_id
            )
            return False

        assignment.status      = "released"
        assignment.released_at = datetime.utcnow()

        # Decrement load counter
        if assignment.pool_number:
            number = assignment.pool_number
            number.active_campaigns_count = max(0, (number.active_campaigns_count or 1) - 1)

        db.session.commit()

        logger.info(
            "CE Number Allocator: Released number for campaign %s", campaign_id
        )
        return True

    @staticmethod
    def get_assignment(campaign_id: int) -> CeCampaignNumberAssignment | None:
        """Get the current active assignment for a campaign."""
        return CeCampaignNumberAssignment.query.filter_by(
            campaign_id=campaign_id, status="active"
        ).first()

    @staticmethod
    def get_number_for_campaign(campaign_id: int) -> str | None:
        """
        Return the assigned phone number string for a campaign.
        Used by the execution engine to set the caller ID.
        """
        assignment = CeNumberAllocator.get_assignment(campaign_id)
        if assignment and assignment.pool_number:
            return assignment.pool_number.number
        return None

    @staticmethod
    def pool_health_summary() -> dict:
        """Return a summary dict for admin monitoring."""
        all_numbers = CeNumberPool.query.all()
        active       = [n for n in all_numbers if n.is_active and n.is_healthy]
        disabled     = [n for n in all_numbers if not n.is_active]
        unhealthy    = [n for n in all_numbers if n.is_active and not n.is_healthy]
        total_load   = sum(n.active_campaigns_count or 0 for n in active)

        return {
            "total_numbers":   len(all_numbers),
            "active_numbers":  len(active),
            "disabled_numbers": len(disabled),
            "unhealthy_numbers": len(unhealthy),
            "total_active_load": total_load,
            "numbers": all_numbers,
        }
