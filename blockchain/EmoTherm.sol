// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// Optional Ethereum commitment contract; the default application uses the Python chain.
contract EmoTherm {
    struct Record { bytes32 imageHash; bytes32 predictionHash; address uploaderAddress; uint256 timestamp; }
    mapping(bytes32 => Record) public records;
    event Committed(bytes32 indexed id, address indexed uploader, bytes32 imageHash, bytes32 predictionHash);
    function commit(bytes32 id, bytes32 imageHash, bytes32 predictionHash) external {
        require(records[id].timestamp == 0, "Record already exists");
        records[id] = Record(imageHash, predictionHash, msg.sender, block.timestamp);
        emit Committed(id, msg.sender, imageHash, predictionHash);
    }
    function verifyRecord(bytes32 id, bytes32 imageHash, bytes32 predictionHash) external view returns (bool) {
        Record storage record = records[id];
        return record.timestamp != 0 && record.imageHash == imageHash && record.predictionHash == predictionHash;
    }
}
