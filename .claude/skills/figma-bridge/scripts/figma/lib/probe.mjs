// probe.mjs — READ-ONLY channel probe: for each candidate channel report the current page, page count,
// page names/ids, and a `fileKey` file fingerprint. Thin CLI over channel-resolve's probeChannel (no
// inline socket/probe loop — the backbone owns that).
//   --channel=<id>   candidate channel (repeatable); FIGMA_CHANNEL also seeds one.
// Zero-dep: Node core + the shared channel-resolve backbone only.
import { probeChannel, folderChannel } from "./channel-resolve.mjs";

export async function run(args) {
  const channels = args.filter((a) => a.startsWith("--channel=")).map((a) => a.split("=")[1]);
  if (process.env.FIGMA_CHANNEL) channels.push(process.env.FIGMA_CHANNEL);
  if (!channels.length) channels.push(folderChannel()); // default the diagnostic to the repo folder name
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const results = await Promise.all(channels.map((c) => probeChannel(c, socketUrl)));
  console.log(JSON.stringify(results, null, 2));
}
