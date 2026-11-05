Attribute VB_Name = "PerFinSelfTest"
' PerFin core shell (task 2c): optional self-test for the Windows/Excel checklist.
' Run it after PerFin_Refresh against a SYNTHETIC data root holding the committed
' fixtures (fixtures\excel_core\reports copied to <data root>\reports). It recalculates,
' compares the summary cells with the values the Linux tests computed independently,
' and inspects protection, links and connections. It writes PASS/FAIL names only
' (no amounts) to <data root>\logs\perfin-selftest.txt and shows a summary.
' The expected values below are checked against the Linux build by tests/excel_core.
Option Explicit

Private results As String
Private failures As Long

Private Sub Report(ByVal name As String, ByVal ok As Boolean, Optional ByVal detail As String = "")
    results = results & IIf(ok, "PASS ", "FAIL ") & name & IIf(Len(detail) > 0, " (" & detail & ")", "") & vbCrLf
    If Not ok Then failures = failures + 1
End Sub

Private Sub ExpectNumber(ByVal name As String, ByVal expected As Double)
    Dim v As Variant
    v = ThisWorkbook.Names(name).RefersToRange.Value
    If IsError(v) Then
        Report name, False, "error value"
    ElseIf Not IsNumeric(v) Then
        Report name, False, "not a number"
    Else
        Report name, Abs(CDbl(v) - expected) < 0.000001
    End If
End Sub

Private Function IsSyntheticRoot(ByVal root As String) As Boolean
    Dim p As String
    p = root & "\perfin-data-dir.json"
    If Len(Dir$(p)) = 0 Then Exit Function
    IsSyntheticRoot = InStr(1, PerFin_ReadTextFile(p), """synthetic""") > 0
End Function

Public Sub PerFin_SelfTest()
    Dim root As String, ws As Worksheet, c As WorkbookConnection, lo As ListObject, cell As Range
    Dim links As Variant, conn As String, ok As Boolean, f As Integer

    results = "PerFin core self-test" & vbCrLf & "Excel " & Application.Version & " build " & Application.Build & _
              " on " & Application.OperatingSystem & vbCrLf
#If Win64 Then
    results = results & "Office bitness: 64-bit" & vbCrLf
#Else
    results = results & "Office bitness: 32-bit" & vbCrLf
#End If
    failures = 0
    root = PerFin_DataRoot()
    If Not IsSyntheticRoot(root) Then
        MsgBox "Self-test needs a synthetic data root (perfin-data-dir.json kind ""synthetic"").", _
               vbExclamation, "PerFin self-test"
        Exit Sub
    End If

    Application.CalculateFull
    ' The synthetic data is dated 2026-06-30, so sources are normally STALE on a later run:
    ' every source must be readable (OK or STALE) and the banner must not claim OK if any is STALE.
    Dim st As Range, anyStale As Boolean, readable As Boolean
    readable = True
    Set lo = PerFin_FindTable("perfin_refresh_status")
    If lo Is Nothing Then
        readable = False
    Else
        For Each st In lo.ListColumns("status").DataBodyRange
            If CStr(st.Value) = "STALE" Then anyStale = True
            If CStr(st.Value) <> "OK" And CStr(st.Value) <> "STALE" Then readable = False
        Next st
    End If
    Report "every report source read (OK or STALE)", readable
    Report "banner never shows OK with a stale or failed source", _
        Left$(CStr(ThisWorkbook.Names("PerFin_Status").RefersToRange.Value), 2) = IIf(anyStale Or Not readable, "ER", "OK")
    ' Expected values for fixtures/excel_core (computed independently by tests/excel_core).
    ExpectNumber "PerFin_TotalAssets", 13700
    ExpectNumber "PerFin_TotalOwed", 300005
    ExpectNumber "PerFin_NetBalance", -286305
    ExpectNumber "PerFin_CardsOwed", 605
    ExpectNumber "PerFin_CardCurrentOwed", 605
    ExpectNumber "PerFin_CardMinimumDue", 60
    ExpectNumber "PerFin_CardUnpaid", 505
    ExpectNumber "PerFin_CardsUnknownLimit", 1
    ExpectNumber "PerFin_TxnCount", 12
    ExpectNumber "PerFin_TxnNet", 1645
    ExpectNumber "PerFin_TxnUnreconciled", 8
    ExpectNumber "PerFin_ReviewRows", 10
    ExpectNumber "PerFin_ReviewAwaiting", 8
    ExpectNumber "PerFin_ReviewErrors", 2
    ExpectNumber "PerFin_ReviewPossibleDuplicates", 1
    ExpectNumber "PerFin_StatementCount", 2
    ExpectNumber "PerFin_StatementsOpen", 1
    ExpectNumber "PerFin_UnreconciledCount", 2
    ExpectNumber "PerFin_UnreconciledAmount", -55
    ExpectNumber "PerFin_StatementOpeningTotal", 450

    ' Text that starts with a formula trigger must stay text after refresh.
    ok = False
    Set lo = PerFin_FindTable("rpt_transactions")
    If Not lo Is Nothing Then
        For Each cell In lo.ListColumns("description").DataBodyRange
            If Left$(CStr(cell.Value), 1) = "=" Then ok = Not cell.HasFormula
        Next cell
    End If
    Report "description starting with = stays text", ok
    ok = False
    Set lo = PerFin_FindTable("rpt_review_queue")
    If Not lo Is Nothing Then
        ok = True
        For Each cell In lo.ListColumns("description").DataBodyRange
            If cell.HasFormula Then ok = False
        Next cell
    End If
    Report "review descriptions (+ - @ TAB CR) stay text", ok

    ok = True
    For Each ws In ThisWorkbook.Worksheets
        If Not ws.ProtectContents Then ok = False
    Next ws
    Report "every sheet protected (UX guard only)", ok
    links = ThisWorkbook.LinkSources(xlExcelLinks)
    Report "no external workbook links", IsEmpty(links)
    ok = True
    For Each c In ThisWorkbook.Connections
        conn = ""
        On Error Resume Next
        conn = c.OLEDBConnection.Connection
        On Error GoTo 0
        If InStr(1, conn, "Microsoft.Mashup.OleDb.1", vbTextCompare) = 0 Or InStr(1, conn, "$Workbook$") = 0 Then ok = False
    Next c
    Report "only Power Query workbook connections", ok

    results = results & failures & " failure(s)" & vbCrLf
    If Len(PerFin_DataRootProblem(root)) > 0 Then
        MsgBox results & "(log not written: data root refused by the location guard)", vbCritical, "PerFin self-test"
        Exit Sub
    End If
    PerFin_EnsureFolder root & "\logs"
    f = FreeFile
    Open root & "\logs\perfin-selftest.txt" For Output As #f
    Print #f, results
    Close #f
    MsgBox results, IIf(failures = 0, vbInformation, vbCritical), "PerFin self-test"
End Sub
