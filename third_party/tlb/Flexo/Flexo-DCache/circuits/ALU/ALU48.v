module ALU #(parameter SIZE = 48) (
    input  [SIZE-1:0] x,       // x-bit input
    input  [SIZE-1:0] y,       // x-bit input
    input  [7:0]  control,     // 8-bit control
    output reg [SIZE-1:0] out  // x-bit output
);

always @(*) begin
    case (control)
        8'b00000001: out = x + y;                 // ADD
        8'b00000010: out = x - y;                 // SUB
        8'b00000100: out = x & y;                 // AND
        8'b00001000: out = x | y;                 // OR
        8'b00010000: out = x ^ y;                 // XOR
        8'b00100000: out = x << y;                // SHL (shift left by value in y)
        8'b01000000: out = x >> y;                // SHR (shift right by value in y)
        8'b10000000: out = ~x;                // SHR (shift right by value in y)
        default:     out = 8'b0;                 // Default to zero
    endcase

		/* ALU that performs multiple things at the same time */
		// out = 8'b0;
    // if (control[0]) out = out | (x + y);        // ADD
    // if (control[1]) out = out | (x - y);        // SUB
    // if (control[2]) out = out | (x & y);        // AND
    // if (control[3]) out = out | (x | y);        // OR
    // if (control[4]) out = out | (x ^ y);        // XOR
    // if (control[5]) out = out | (x << y);       // SHL
    // if (control[6]) out = out | (x >> y);       // SHR
end

endmodule
