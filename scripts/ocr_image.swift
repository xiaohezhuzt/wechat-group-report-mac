import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count == 2 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = false
let handler = VNImageRequestHandler(url: url, options: [:])
do {
    try handler.perform([request])
    let items = (request.results ?? []).compactMap { observation -> [String: Any]? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence,
                "bbox": [b.origin.x, b.origin.y, b.width, b.height]]
    }
    let result: [String: Any] = ["engine": "Apple Vision", "status": "machine_ocr", "lines": items]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]))
} catch {
    FileHandle.standardOutput.write(Data("{\"status\":\"unavailable\",\"reason\":\"vision_request_failed\"}".utf8))
    exit(1)
}
