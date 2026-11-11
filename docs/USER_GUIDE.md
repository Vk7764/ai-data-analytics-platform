# User Guide

This guide walks you through the AI Data Analytics Platform from first sign-in to sharing results.

## 1. Sign up or log in

- Click **Sign Up Free** on the home page to create an account. If email verification is enabled in your deployment, verify your email before using all features.
- Returning users click **Log In**. If a password reset option is available, use **Forgot password?** to recover access.
- AI features require a signed-in user and are subject to the configured AI quota.

## 2. Upload a dataset or use the sample dataset

- In the **Upload a Dataset** section, choose a CSV, Excel, JSON, or SQL file and click **Upload**.
- New here? Click **Try with Sample Data** to explore the profile, KPIs, charts, and insights with a ready-made dataset.
- Large files may take longer to process. Files above the configured maximum upload size cannot be uploaded.

## 3. Review the profile and rows

- **Dataset Overview** shows rows, columns, duplicate rows, and a health score, followed by the column list.
- **Rows** shows the data page by page. Use the search box, the rows-per-page selector, and the column sort controls. The search request is debounced, so it pauses briefly while you type.
- **Column Summary** lets you choose a column and see its statistics or top values.
- **Pivot / Group-By Summary** groups a numeric column by a category, with an optional split and a choice of aggregation.

## 4. Clean the data safely

- Choose a cleaning action, or click **Clean All (Safe Fixes)** if available. A **preview** appears first and shows rows before and after, cells changed, columns affected, warnings, and sample changes.
- Click **Apply Changes** to apply, or **Cancel** to close the preview without changing anything.
- Use **Undo** to revert recent applied changes within the retained undo history.
- **View change log** shows applied cleaning actions with their column and time where available.

## 5. Analysis dashboard

- **KPI cards** show totals, averages, medians, minimums, and maximums. The **How these metrics were calculated** panel explains how each figure was produced.
- **Correlation matrix** highlights strong positive and strong negative relationships. Correlation does not prove cause.
- **Charts** can be switched between automatic, custom X/Y, histogram, and pivot views where available. Use **Download Chart CSV** to export the chart data.
- **Saved analyses** let you save the current view and load it later. A warning appears if the data has changed since you saved it.
- **Generate AI Insight** writes a short narrative. It uses AI quota according to the configured policy and may reuse cached output when the dataset has not changed.

## 6. Time series, forecast, anomalies, root cause, and chat

- **Time Series Explorer** may require a premium plan. Where available, click a bar to zoom from year to month, week, day, and hour. Moving averages and CSV export may be available.
- **Forecast**: choose a date column and a value column, then generate a short forecast with an uncertainty band. The methodology panel lists assumptions and limitations where provided.
- **Anomaly Detection**: choose the z-score or IQR method and a sensitivity level. Detection is deterministic; **Explain with AI** is optional and may use AI quota.
- **Root Cause Analysis**: choose a metric and optionally include or exclude dimensions. The breakdown shows which groups explain the most variation. AI explanation is optional and may use AI quota.
- **Chat With Your Data**: ask questions in plain language. Available modes depend on your plan and deployment configuration. Long result sets may show a bounded preview.

## 7. Understand AI labels and freshness

- Text produced by AI is marked **AI-generated** and carries a note to verify important figures against the data.
- AI output may be cached until the dataset changes. Regenerate it after cleaning or editing data.
- KPI cards, charts, anomaly lists, root-cause tables, and methodology panels are calculated directly from the data. They are not AI output.
- Your AI request limit is shown in the header badge where configured. It resets according to the deployed quota policy.

## 8. Generate reports

- Use **Generate Report** to download a PDF, Excel, PowerPoint, or CSV file. Additional export formats such as JSON or SQL may be available depending on plan or deployment configuration.
- Reports include a methodology and data-lineage section for deterministic parts.
- AI-written sections, such as executive summary, recommendations, and explanations, are labelled as AI-generated.
- Premium users may be able to add a logo and brand colour under **Report Branding**, and schedule recurring email or webhook exports where the scheduler is enabled.

## 9. Share a read-only link

- In the dataset list or history drawer, click **Share** on a dataset.
- Optionally add a label and choose an expiry of 1 to 90 days, with a default of 30 days, then click **Create link**.
- **Copy the link immediately.** It is shown only once and cannot be displayed again.
- Anyone with the link sees a read-only preview of up to 10 rows and a profile summary. They cannot edit, clean, download the full dataset, or use AI features.
- Under **Active links** you can see each link's label and expiry, and click **Revoke** to disable it at once. Expired and revoked links stop working.

## 10. Privacy limits

- A share link exposes only a small preview and a profile summary, not your account details.
- Do not share datasets that contain sensitive personal information, such as identity numbers, financial details, or health records, unless you accept that risk.
- Remove sensitive columns before uploading, or clean them out of the dataset, when the data does not need to be analysed.
- Deleting a dataset removes its share links and saved analyses. Other linked records, such as chat history or scheduled exports, are handled according to the current deployment and cleanup behavior.