import assert from "node:assert/strict";
import { blobatar } from "blobatar";

const seed = "stored-avatar-seed-42";
assert.equal(blobatar(seed), blobatar(seed));
assert.notEqual(blobatar(seed), blobatar("another-avatar-seed"));
console.log("PASS Blobatar uses a stable stored seed independently of profile names");
