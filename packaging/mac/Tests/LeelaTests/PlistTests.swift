import Foundation
import Testing

/// Finder's Open With list for the thin app; `make plist` writes these keys from leela.workspace.doc_types.
@Suite struct PlistTests {
    let plist: [String: Any] = {
        let u = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("../../Resources/Info.plist")
        return (try? PropertyListSerialization.propertyList(from: Data(contentsOf: u), format: nil)) as? [String: Any] ?? [:]
    }()
    var types: [[String: Any]] { plist["CFBundleDocumentTypes"] as? [[String: Any]] ?? [] }
    func row(_ name: String) -> [String: Any] { types.first { $0["CFBundleTypeName"] as? String == name } ?? [:] }
    func utis(_ name: String) -> Set<String> { Set(row(name)["LSItemContentTypes"] as? [String] ?? []) }

    @Test func everyKindATabShowsIsAnAlternateHandler() {
        #expect(plist["CFBundleIdentifier"] as? String == "org.vedicreader.leela")
        #expect(types.count > 5 && types.allSatisfy { $0["LSHandlerRank"] as? String == "Alternate" })
        #expect(utis("Folder") == ["public.folder"])
        #expect(utis("Image").isSuperset(of: ["public.png", "public.jpeg", "public.svg-image"]) && row("Image")["CFBundleTypeRole"] as? String == "Viewer")
        #expect(utis("PDF document") == ["com.adobe.pdf"] && row("PDF document")["CFBundleTypeRole"] as? String == "Viewer")
        #expect(utis("Word, PowerPoint or Excel file") == ["org.openxmlformats.wordprocessingml.document", "org.openxmlformats.presentationml.presentation",
                                                          "org.openxmlformats.spreadsheetml.sheet", "org.openxmlformats.spreadsheetml.sheet.macroenabled"])
        #expect(utis("Text file").isSuperset(of: ["public.python-script", "net.daringfireball.markdown"]) && row("Text file")["CFBundleTypeRole"] as? String == "Editor")
        #expect(!types.contains { Set($0["LSItemContentTypes"] as? [String] ?? []).intersection(["public.image", "public.data", "public.item", "public.plain-text"]).count > 0 })
    }

    @Test func aNotebookHasAnImportedTypeAndItsExtension() {
        let imp = plist["UTImportedTypeDeclarations"] as? [[String: Any]] ?? []
        let nb = imp.first { $0["UTTypeIdentifier"] as? String == "org.jupyter.ipynb" }
        #expect((nb?["UTTypeTagSpecification"] as? [String: Any])?["public.filename-extension"] as? [String] == ["ipynb"])
        #expect(utis("Jupyter notebook") == ["org.jupyter.ipynb"] && row("Jupyter notebook by extension")["CFBundleTypeExtensions"] as? [String] == ["ipynb"])
        #expect((row("Text file by extension")["CFBundleTypeExtensions"] as? [String] ?? []).contains("ts"))
    }
}
