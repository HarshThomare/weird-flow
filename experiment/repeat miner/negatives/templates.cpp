/* Same template body instantiated at many constants.
 * Register/constant abstraction can make these look like one repeated gate.
 */
template <int N>
__attribute__((noinline, used)) int roll(int x) {
    int a = x + N;
    int b = (a << (N & 7)) ^ (a >> 1);
    int c = b * (N + 3) + x;
    return (c ^ N) + (a >> (N & 3));
}

template int roll<1>(int);
template int roll<2>(int);
template int roll<3>(int);
template int roll<4>(int);
template int roll<5>(int);
template int roll<6>(int);
template int roll<7>(int);
template int roll<8>(int);
template int roll<9>(int);
template int roll<10>(int);
template int roll<11>(int);
template int roll<12>(int);
