SET join_collapse_limit = 1;
SELECT count(*)
FROM (((aka_title CROSS JOIN (title CROSS JOIN char_name)) CROSS JOIN kind_type) CROSS JOIN movie_info_idx) CROSS JOIN cast_info
WHERE char_name.surname_pcode = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info_idx.movie_id = title.id
  AND title.kind_id = kind_type.id;
