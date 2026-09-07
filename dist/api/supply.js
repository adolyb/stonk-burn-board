// Serverless proxy for a single RPC call.
//
// The public Solana endpoints reject requests that carry a browser Origin (403),
// so the page cannot read the chain directly once it is deployed. This function
// runs server-side, where no Origin is attached.
//
// It is deliberately NOT a general RPC proxy: the method and the mint are fixed
// here, so the deployment cannot be used as someone else's free RPC.

const RPC_URL = process.env.STONK_RPC_URL || 'https://api.mainnet-beta.solana.com';
const MINT = process.env.STONK_MINT || '6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx';

module.exports = async (req, res) => {
  try {
    const upstream = await fetch(RPC_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'getTokenSupply',
        params: [MINT],
      }),
    });

    const payload = await upstream.json();
    res.setHeader('Cache-Control', 'public, max-age=0, must-revalidate');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(upstream.ok ? 200 : 502).json(payload);
  } catch (err) {
    res.status(502).json({ error: { message: String((err && err.message) || err) } });
  }
};
