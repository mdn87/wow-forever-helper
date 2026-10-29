# Local dictation of a bounded, in-memory WAV. This helper never opens a microphone.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    Add-Type -AssemblyName System.Speech
    Add-Type -ReferencedAssemblies ([System.Speech.Recognition.SpeechRecognitionEngine].Assembly.Location) -TypeDefinition @'
using System;
using System.IO;
using System.Collections.Generic;
using System.Speech.Recognition;
using System.Threading;
public static class CompanionDictation {
    public static string Read(byte[] audio) {
        using (var stream = new MemoryStream(audio))
        using (var engine = new SpeechRecognitionEngine())
        using (var finished = new ManualResetEvent(false)) {
            var words = new List<string>();
            Exception failure = null;
            engine.LoadGrammar(new DictationGrammar());
            engine.SetInputToWaveStream(stream);
            engine.SpeechRecognized += (sender, result) => { words.Add(result.Result.Text); };
            engine.RecognizeCompleted += (sender, result) => { failure = result.Error; finished.Set(); };
            engine.RecognizeAsync(RecognizeMode.Multiple);
            if (!finished.WaitOne(35000)) { engine.RecognizeAsyncCancel(); throw new TimeoutException(); }
            if (failure != null) { throw failure; }
            return String.Join(" ", words);
        }
    }
}
'@
    $encoded = [Console]::In.ReadToEnd()
    if ($encoded.Length -gt 1300000) { throw 'Oversized recording' }
    $bytes = [Convert]::FromBase64String($encoded)
    @{text=[CompanionDictation]::Read($bytes)} | ConvertTo-Json -Compress
} catch {
    @{error='Local speech recognition failed'} | ConvertTo-Json -Compress
    exit 1
}
