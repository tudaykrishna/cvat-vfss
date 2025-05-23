// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

type CamelizeString<T extends PropertyKey, C extends string = ''> =
T extends string ? string extends T ? string :
    T extends `${infer F}_${infer R}` ?
        CamelizeString<Capitalize<R>, `${C}${F}`> : (T extends 'Id' ? `${C}${'ID'}` : `${C}${T}`) : T;

type CamelizeStringV2<T extends PropertyKey, C extends string = ''> =
    T extends string
        ? string extends T
            ? string
            : T extends `${infer F}_${infer R}`
                ? CamelizeStringV2<Capitalize<R>, `${C}${Lowercase<F>}`>
                : `${C}${T}`
        : T;

// https://stackoverflow.com/a/63715429
// Use https://stackoverflow.com/a/64933956 for snake-ization
/**
 * Returns the input type with fields in CamelCase
 */
export type Camelized<T> = { [K in keyof T as CamelizeString<K>]: T[K] };
export type CamelizedV2<T> = { [K in keyof T as CamelizeStringV2<K>]: T[K] };
