' Helper function to parse CSV while handling quotes
Function SplitCSV(ByVal csv As String) As Variant
    Dim parts As Object: Set parts = CreateObject("Scripting.Dictionary")
    Dim buffer As String: buffer = ""
    Dim inQuotes As Boolean: inQuotes = False
    Dim i As Long
    
    ' Parse CSV character by character
    For i = 1 To Len(csv)
        Dim char As String: char = Mid(csv, i, 1)
        
        If char = """" Then
            inQuotes = Not inQuotes
        ElseIf char = "," And Not inQuotes Then
            parts(parts.Count) = Trim(buffer)
            buffer = ""
        Else
            buffer = buffer & char
        End If
    Next i
    
    ' Capture final part
    If Len(buffer) > 0 Then parts(parts.Count) = Trim(buffer)
    SplitCSV = parts.Items
End Function

' Helper function to safely convert a CSV value to a number
Function SafeConvertToNumber(ByVal value As String, ByVal isNegative As Boolean) As Double
    ' Remove surrounding quotes if present
    If Left(value, 1) = """" And Right(value, 1) = """" Then
        value = Mid(value, 2, Len(value) - 2)
    End If
    
    ' Replace dot with comma if necessary (for European locales)
    If InStr(1, value, altDec) > 0 And Application.DecimalSeparator = altDec Then
        value = Replace(value, altDec, localDec)
    End If
    
    ' Convert to number if it's numeric
    If IsNumeric(value) Then
        If isNegative Then
            SafeConvertToNumber = -CDbl(value)
        Else
            SafeConvertToNumber = CDbl(value)
        End If
    Else
        SafeConvertToNumber = 0
    End If
End Function
