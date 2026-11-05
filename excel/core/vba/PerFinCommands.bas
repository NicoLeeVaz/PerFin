Attribute VB_Name = "PerFinCommands"
' PerFin core shell (task 2c): review-sheet command entry point.
' The workbook never writes the ledger. These macros only write a contract `command`
' draft (approve_rows / reject_rows, contract 1.0.0) to <data root>\commands\drafts.
' The validator (python -m perfin_excel_core command promote) checks it with
' perfin_contracts and moves it to <data root>\commands\outbox; the PerFin repository
' re-validates and applies it. Application-owned perfin_batch_versions supplies
' optimistic versions; absent tokens refuse drafts and stale tokens fail in Access.
Option Explicit

Private Const ISSUED_BY As String = "excel_core:review_sheet"
Private Const CONTRACT_VERSION As String = "1.0.0"

Public Sub PerFin_ApproveSelectedRows()
    BuildReviewDraft "approve_rows"
End Sub

Public Sub PerFin_RejectSelectedRows()
    BuildReviewDraft "reject_rows"
End Sub

Private Function IsContractId(ByVal s As String) As Boolean
    Dim i As Long
    If Len(s) = 0 Or Len(s) > 64 Then Exit Function
    If Not (Left$(s, 1) Like "[A-Za-z0-9]") Then Exit Function
    For i = 2 To Len(s)
        If Not (Mid$(s, i, 1) Like "[A-Za-z0-9_.:-]") Then Exit Function
    Next i
    IsContractId = True
End Function

Private Function BatchVersion(ByVal batch As String) As Long
    Dim lo As ListObject, rw As Range, value As Variant
    On Error GoTo Missing
    Set lo = PerFin_FindTable("perfin_batch_versions")
    If lo Is Nothing Then Exit Function
    If lo.DataBodyRange Is Nothing Then Exit Function
    For Each rw In lo.DataBodyRange.Rows
        If CStr(rw.Cells(1, lo.ListColumns("batch_id").Index).Value) = batch Then
            value = rw.Cells(1, lo.ListColumns("row_version").Index).Value
            If Not IsNumeric(value) Then Exit Function
            If value < 1 Or value <> Int(value) Or value > 2147483647 Then Exit Function
            BatchVersion = CLng(value)
            Exit Function
        End If
    Next rw
Missing:
End Function

Private Sub BuildReviewDraft(ByVal commandType As String)
    Dim lo As ListObject, sel As Range, area As Range, rw As Range
    Dim cBatch As Long, cRow As Long, cErr As Long, cDup As Long, idx As Long
    Dim batch As String, b As String, v As Variant, problems As String, version As Long
    Dim nums() As Long, n As Long, i As Long, j As Long, t As Long, dup As Boolean
    Dim reason As String, id As String, json As String, list As String, folder As String, why As String

    ' Location guard first: nothing (batch id, reason) is written to a Git checkout,
    ' sync folder, network path or a folder without the 1c data-root marker.
    why = PerFin_DataRootProblem(PerFin_DataRoot())
    If Len(why) > 0 Then
        MsgBox "No command written. The PerFin data root is refused: " & why & "." & vbLf & _
               "Choose a local folder outside Git checkouts and sync folders (Settings!B4) that holds " & _
               PERFIN_DATA_DIR_MARKER & ".", vbCritical, "PerFin review"
        Exit Sub
    End If
    Set lo = PerFin_FindTable("rpt_review_queue")
    If lo Is Nothing Then Exit Sub
    If lo.DataBodyRange Is Nothing Or TypeName(Selection) <> "Range" Then
        MsgBox "Select one or more rows of the review table first.", vbExclamation, "PerFin review"
        Exit Sub
    End If
    Set sel = Intersect(Selection, lo.DataBodyRange)
    If sel Is Nothing Then
        MsgBox "Select one or more rows of the review table first.", vbExclamation, "PerFin review"
        Exit Sub
    End If
    cBatch = lo.ListColumns("batch_id").Index
    cRow = lo.ListColumns("row_number").Index
    cErr = lo.ListColumns("error_codes").Index
    cDup = lo.ListColumns("duplicate_status").Index

    ReDim nums(1 To lo.ListRows.Count)
    For Each area In sel.Areas
        For Each rw In area.Rows
            idx = rw.Row - lo.HeaderRowRange.Row
            b = CStr(lo.DataBodyRange.Cells(idx, cBatch).Value)
            v = lo.DataBodyRange.Cells(idx, cRow).Value
            If Not IsContractId(b) Then
                problems = problems & vbLf & "  table row " & idx & ": batch_id is not a contract id"
            ElseIf Len(batch) > 0 And b <> batch Then
                problems = problems & vbLf & "  select rows from one batch at a time"
            ElseIf Not IsNumeric(v) Then
                problems = problems & vbLf & "  table row " & idx & ": row_number is not a number"
            ElseIf v < 1 Or v <> Int(v) Then
                problems = problems & vbLf & "  table row " & idx & ": row_number must be a whole number >= 1"
            Else
                batch = b
                If commandType = "approve_rows" Then
                    If Len(CStr(lo.DataBodyRange.Cells(idx, cErr).Value)) > 0 Then _
                        problems = problems & vbLf & "  row " & v & " has errors; fix or reject it"
                    If CStr(lo.DataBodyRange.Cells(idx, cDup).Value) = "possible" Then _
                        problems = problems & vbLf & "  row " & v & " is a possible duplicate; resolve it first"
                End If
                dup = False
                For i = 1 To n
                    If nums(i) = CLng(v) Then dup = True
                Next i
                If Not dup Then
                    n = n + 1
                    nums(n) = CLng(v)
                End If
            End If
        Next rw
    Next area
    If Len(problems) > 0 Or n = 0 Then
        MsgBox "No command written:" & problems, vbExclamation, "PerFin review"
        Exit Sub
    End If

    version = BatchVersion(batch)
    If version < 1 Then
        MsgBox "No command written: refresh the application reports and the perfin_batch_versions query first.", vbExclamation, "PerFin review"
        Exit Sub
    End If

    If commandType = "reject_rows" Then
        reason = Trim$(InputBox("Reason for rejecting " & n & " row(s) (1 to 120 characters):", "PerFin review"))
        If Len(reason) = 0 Or Len(reason) > 120 Then
            MsgBox "No command written: a reason of 1 to 120 characters is required.", vbExclamation, "PerFin review"
            Exit Sub
        End If
    End If

    For i = 2 To n            ' ascending, as the Python builder writes them
        t = nums(i)
        j = i - 1
        Do While j >= 1
            If nums(j) <= t Then Exit Do
            nums(j + 1) = nums(j)
            j = j - 1
        Loop
        nums(j + 1) = t
    Next i
    For i = 1 To n
        list = list & IIf(i > 1, ", ", "") & CStr(nums(i))
    Next i

    id = PerFin_NewUuid()
    json = "{""contract"": ""perfin"", ""contract_version"": """ & CONTRACT_VERSION & """, " & _
        """document_type"": ""command"", ""command_id"": """ & id & """, " & _
        """command_type"": """ & commandType & """, ""issued_at"": """ & PerFin_UtcTimestamp() & """, " & _
        """issued_by"": """ & ISSUED_BY & """, ""payload"": {""batch_id"": " & PerFin_JsonString(batch) & _
        ", ""row_numbers"": [" & list & "]" & _
        IIf(commandType = "reject_rows", ", ""reason"": " & PerFin_JsonString(reason), "") & _
        "}, ""expected_versions"": [{""entity"": ""batch"", ""entity_id"": " & _
        PerFin_JsonString(batch) & ", ""row_version"": " & CStr(version) & "}]}"

    folder = PerFin_CheckedDataRoot() & "\commands\drafts"   ' guard re-checked just before writing
    PerFin_EnsureFolder folder
    PerFin_WriteNewAsciiFile folder & "\" & id & ".json", json
    MsgBox "Command draft written (" & commandType & ", " & n & " row(s))." & vbLf & _
           "Nothing in the ledger has changed. Validate it with:" & vbLf & _
           "  python -m perfin_excel_core command promote --data-root """ & PerFin_DataRoot() & """" & vbLf & _
           "then let PerFin apply the outbox and refresh this workbook.", vbInformation, "PerFin review"
End Sub
