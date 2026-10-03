#!/bin/bash

PROJECT_ROOT=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/../../

# configurations
min_mul_rounds=1
max_mul_rounds=50

# create a build dir if not exist
if ! test -d $PROJECT_ROOT/reproduce/build; then
    mkdir $PROJECT_ROOT/reproduce/build
fi

# compile the circuits into LLVM IR
make -C $PROJECT_ROOT/circuits

compile_circuit() {
    local circuit_name="$1"
    local dir="$2"
    local wr_offset=$3
    local verilog="${4:-}"

    # create a dir for the circuit if not exist
    if ! test -d $PROJECT_ROOT/reproduce/build/$circuit_name; then
        mkdir $PROJECT_ROOT/reproduce/build/$circuit_name
    fi

    # config the Flexo compiler and compile the circuit with 1 mul_round
    export WR_HIT_THRESHOLD=121 DUAL_WM_MAX_INPUT=3 RET_WM_MUL_ROUNDS=1 RET_WM_MUL_SIZE=32
    if [ -n "$verilog" ]; then
        export WM_CIRCUIT_FILE=$verilog
    else
        export WM_CIRCUIT_FILE=""
    fi

    # run the Flexo compiler and create an executable
    outfile=$PROJECT_ROOT/reproduce/build/$circuit_name/$circuit_name-1.ll
    echo "[$circuit_name]" >> $PROJECT_ROOT/reproduce/build/circuits.log
    opt-17 -load-pass-plugin $PROJECT_ROOT/build/lib/libFlexo.so -passes="create-WMs" \
        $dir/$circuit_name.ll -S -o $outfile \
        | tee -a $PROJECT_ROOT/reproduce/build/circuits.log
    echo "" >> $PROJECT_ROOT/reproduce/build/circuits.log
    
    # generate circuits with different transient window sizes
    # (by adjusting the number of mul instructions)
    for mul_round in $(seq $(expr $min_mul_rounds) $max_mul_rounds); do

        # copy outfile
        newfile=$PROJECT_ROOT/reproduce/build/$circuit_name/$circuit_name-$mul_round.ll
        cp $outfile $newfile

        # find the line where division starts
        lineNum=$(awk "/mod_ret_addr:/{ print NR; exit }" $newfile)
        let lineNum++

        # Parse generated assembly from python
        asmLines=()
        while IFS= read -r line; do
            asmLines+=("$line")
        done < <(python3 $PROJECT_ROOT/reproduce/scripts/generate_llvm_asm.py $mul_round 512 32)

        sed -i "${lineNum}s/.*/module asm \"${asmLines[0]}\"/" $newfile
        let lineNum++

        for ((i=2; i<${#asmLines[@]}; i++)); do
            line="${asmLines[i]}"
            [[ -z "$line" ]] && continue
            sed -i "${lineNum}a module asm \"${line}\"" $newfile
            let lineNum++
        done
        
        # LLVM IR to executable
        clang-17 $newfile ${PROJECT_ROOT}lib/other/*.ll -o $PROJECT_ROOT/reproduce/build/$circuit_name/$circuit_name-$mul_round.elf -lm -lstdc++
        # delete LLVM IR to save space
        # rm $newfile
        echo -ne "Progress ($circuit_name): ${mul_round}/${max_mul_rounds}\r"
    done
    echo -ne '\n'
}

# compile single circuits (5.1 & 5.2)
compile_circuit ALU $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU.v
compile_circuit sha1_round_composed $PROJECT_ROOT/circuits/SHA1 576
compile_circuit aes_round $PROJECT_ROOT/circuits/AES 448
compile_circuit simon25 $PROJECT_ROOT/circuits/Simon 448
compile_circuit simon32 $PROJECT_ROOT/circuits/Simon 448
compile_circuit ALU8 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU8.v
compile_circuit ALU9 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU9.v
compile_circuit ALU10 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU10.v
compile_circuit ALU11 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU11.v
compile_circuit ALU12 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU12.v
compile_circuit ALU14 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU14.v
compile_circuit ALU16 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU16.v
compile_circuit ALU24 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU24.v
compile_circuit ALU32 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU32.v
compile_circuit ALU34 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU34.v
compile_circuit ALU36 $PROJECT_ROOT/circuits/ALU  1088 $PROJECT_ROOT/circuits/ALU/ALU36.v

# compile composed circuits (5.3)
compile_circuit sha1_2blocks_composed $PROJECT_ROOT/circuits/SHA1 576
compile_circuit aes_block $PROJECT_ROOT/circuits/AES 448

