import { useState } from "react";
import { Button, Field, Input, Modal } from "./lms-ui";
import { errorMessage, leaveRequests } from "../lib/api";
import { showToast } from "../lib/toast";

/**
 * Reviewing a pending leave request — used identically from the Leave
 * Requests page and the central Approvals queue, so the decision logic is
 * never duplicated between them. Lets the approver adjust the requested
 * date range before approving (Part 9.2), not only a binary approve-as-is
 * or reject.
 */
export function LeaveDecisionModal({ leave, onClose, onDecided }: { leave: any; onClose: () => void; onDecided: () => void }) {
  const [startDate, setStartDate] = useState(leave.start_date);
  const [endDate, setEndDate] = useState(leave.end_date);
  const [busy, setBusy] = useState("");

  const datesChanged = startDate !== leave.start_date || endDate !== leave.end_date;

  async function decide(action: "approve" | "reject") {
    if (action === "approve" && endDate < startDate) {
      showToast("The end date cannot be before the start date.", "danger");
      return;
    }
    let rejection_reason: string | undefined;
    if (action === "reject") {
      rejection_reason = window.prompt("Reason for rejection:") || undefined;
      if (!rejection_reason) return;
    }
    setBusy(action);
    try {
      if (action === "reject") {
        await leaveRequests.reject(leave.id, rejection_reason);
      } else {
        await leaveRequests.approve(leave.id, datesChanged ? { start_date: startDate, end_date: endDate } : undefined);
      }
      showToast(`Leave request ${action === "approve" ? "approved" : "rejected"}.`, "success");
      onDecided();
      onClose();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal
      title={`Review ${leave.employee_name || "this"} leave request`}
      description={`${leave.leave_type} — requested ${leave.start_date} to ${leave.end_date}`}
      onClose={onClose}
    >
      <div className="space-y-3">
        {leave.reason ? <p className="text-sm text-muted-foreground">Reason given: {leave.reason}</p> : null}
        <Field label="Start date" hint="Adjust before approving if needed.">
          <Input type="date" value={startDate} onChange={(e: any) => setStartDate(e.target.value)} />
        </Field>
        <Field label="End date">
          <Input type="date" value={endDate} onChange={(e: any) => setEndDate(e.target.value)} />
        </Field>
        <div className="flex gap-2 pt-2">
          <Button disabled={Boolean(busy)} onClick={() => decide("approve")} className="flex-1">
            {busy === "approve" ? "Approving…" : datesChanged ? "Approve with these dates" : "Approve"}
          </Button>
          <Button variant="outline" disabled={Boolean(busy)} onClick={() => decide("reject")}>
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
