param([Parameter(Mandatory = $true)][string]$ImagePath)

# Internal OCR transport only. The Python caller captures this output in memory
# and publishes counts/reasons, never the extracted text. No model or network is used.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

    $taskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1

    function Wait-Operation($Operation, [Type]$ResultType) {
        $task = $taskMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
        if (-not $task.Wait(10000)) { throw 'OCR operation deadline' }
        return $task.Result
    }

    $imageFile = Wait-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $stream = Wait-Operation ($imageFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Wait-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Wait-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
            if ($null -eq $engine) { throw 'OCR language unavailable' }
            $result = Wait-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            @{ available = $true; text = $result.Text } | ConvertTo-Json -Compress
        } finally { $bitmap.Dispose() }
    } finally { $stream.Dispose() }
} catch {
    # Do not emit exception details, paths, or partially recognized source copy.
    @{ available = $false } | ConvertTo-Json -Compress
    exit 1
}
