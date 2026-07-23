# Demonstration workflows

Every demonstration should show the source, last checkpoint, validation status, and the
fact that BQE CORE remains the system of record.

## Available now

- Reconcile a bounded date range to BQE time and expense screens.
- Compare historical billable and nonbillable hours by employee and project.
- Review the projects that absorbed the most recent effort.
- Show changes in project mix and employee workload by month.
- Combine authorized allocation history with actual time history.
- Generate a traceable management brief and machine-readable planning context.
- Identify data gaps, stale history, concentrated staffing, and review candidates.

## Planning workflow

1. Synchronize the latest authorized BQE history.
2. Validate warehouse integrity and review unavailable resources.
3. Export planning context.
4. Add current commitments, deadlines, waiting periods, leave, and proposed work from the
   maintained weekly planning input.
5. Ask the AI assistant to summarize capacity, conflicts, and options.
6. A manager reviews and decides; approved changes remain in the operational planning
   process, not in an automatic BQE write path.

## Dependent on tenant data or additional sources

- Reliable forward capacity requires current allocations or another maintained planning
  input plus standard hours and approved leave.
- Exact revenue, WIP, payroll burden, and accounting profitability may require data not
  exposed by the public API.
- Contract terms or constraints stored only in attachments, notes, or external systems
  must be supplied separately.
- The public API does not reproduce every standard or custom BQE report calculation.

## Deliberately excluded

- `readwrite:core`
- Automatic changes to time, invoices, projects, allocations, or status
- Unrestricted raw data sent to a general chat
- Financial estimates presented as audited facts
- AI-generated schedules treated as approved commitments
